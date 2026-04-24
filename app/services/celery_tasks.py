# app/services/celery_tasks.py
from celery import Celery
from app.core.config import settings
from app.core.logger import get_logger
from app.services.rag_service import rag_service
from app.services.document_processor import document_processor
import json
import re
import requests
import asyncio
import math
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import select, update, create_engine
from firecrawl import FirecrawlApp
from pydantic import BaseModel, Field
from agno.agent import Agent
from langchain_text_splitters import RecursiveCharacterTextSplitter
from agno.models.openai import OpenAILike
from agno.tools.exa import ExaTools
from agno.tools.duckduckgo import DuckDuckGoTools
from app.models.competitor_analysis import CompetitorAnalysisTask, AnalysisStatus
import io
import os
import uuid
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import base64
from matplotlib import rcParams
from app.models.analysis_chart import AnalysisChart
from langchain_core.documents import Document
from datetime import datetime, timezone

logger = get_logger(__name__)

# 配置 Matplotlib 中文字体
try:
    rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    rcParams['axes.unicode_minus'] = False
except Exception as e:
    logger.warning(f"字体配置失败: {e}")

celery_app = Celery(
    "deepseek_chat",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


# ---------- 图表生成辅助函数 ----------
def clean_llm_json_response(llm_text: str) -> str:
    """清洗 LLM 返回的文本，移除可能的 Markdown 代码块标记，提取纯 JSON 字符串。"""
    cleaned = re.sub(r'^```json\s*', '', llm_text.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    return cleaned.strip()


def parse_llm_chart_response(llm_text: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 返回的图表配置 JSON。返回 None 表示解析失败。"""
    try:
        cleaned = clean_llm_json_response(llm_text)
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"LLM JSON 解析失败: {e}, 原始响应: {llm_text[:200]}...")
        return None


def fallback_chart_params(df: pd.DataFrame) -> Dict[str, str]:
    """当 LLM 推荐失败时，根据 DataFrame 的结构自动生成合理的图表参数。"""
    cat_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
    num_cols = df.select_dtypes(include=['number']).columns.tolist()

    if cat_cols and num_cols:
        return {
            "chart_type": "bar",
            "x_column": cat_cols[0],
            "y_column": num_cols[0],
            "title": f"{num_cols[0]} by {cat_cols[0]}"
        }
    elif num_cols:
        # 如果有索引名且索引不是默认整数，使用索引作为 x
        if df.index.name and df.index.name != "index":
            return {
                "chart_type": "line",
                "x_column": df.index.name,
                "y_column": num_cols[0],
                "title": f"{num_cols[0]} Trend"
            }
        else:
            # 将索引重置为列
            df_reset = df.reset_index()
            first_col = df_reset.columns[0]
            return {
                "chart_type": "bar" if len(df) <= 20 else "line",
                "x_column": first_col,
                "y_column": num_cols[0],
                "title": f"{num_cols[0]} Distribution"
            }
    else:
        raise ValueError("无法自动生成图表参数：DataFrame 中既没有分类列也没有数值列。")


def validate_and_prepare_data(df: pd.DataFrame, x_col: str, y_col: str, chart_type: str) -> pd.DataFrame:
    # 处理 x_col = "index" 或 df.index.name 的情况
    if x_col.lower() == "index":
        # 如果索引没有名称，为其命名为 "index"
        if df.index.name is None:
            df.index.name = "index"
        x_col = df.index.name
        plot_df = df.reset_index()
    else:
        if x_col not in df.columns and x_col != df.index.name:
            raise KeyError(f"X 轴列 '{x_col}' 不存在。可用列: {list(df.columns)}")
        plot_df = df.copy()
        if x_col == plot_df.index.name:
            plot_df = plot_df.reset_index()

    # 处理 y_col
    if y_col not in plot_df.columns:
        raise KeyError(f"Y 轴列 '{y_col}' 不存在。可用列: {list(plot_df.columns)}")

    plot_df[y_col] = pd.to_numeric(plot_df[y_col], errors='coerce')
    plot_df = plot_df.dropna(subset=[y_col])

    if chart_type == "line" and len(plot_df) < 2:
        raise ValueError(f"折线图需要至少 2 个数据点，当前只有 {len(plot_df)} 行。")

    return plot_df


def draw_chart(plot_df: pd.DataFrame, chart_type: str, x_col: str, y_col: str, title: str) -> plt.Figure:
    """根据参数绘制 matplotlib 图表，返回 Figure 对象。"""
    fig, ax = plt.subplots(figsize=(10, 6))

    if chart_type == "bar":
        plot_df.plot.bar(x=x_col, y=y_col, ax=ax, legend=False)
    elif chart_type == "line":
        plot_df.plot.line(x=x_col, y=y_col, ax=ax, marker='o')
    elif chart_type == "scatter":
        plot_df.plot.scatter(x=x_col, y=y_col, ax=ax)
    elif chart_type == "pie":
        plot_df.set_index(x_col)[y_col].plot.pie(ax=ax, autopct='%1.1f%%', ylabel='')
    else:
        raise ValueError(f"不支持的图表类型: {chart_type}")

    ax.set_title(title)
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    plt.tight_layout()
    return fig


def fig_to_base64(fig: plt.Figure) -> str:
    """将 matplotlib Figure 转换为 base64 编码的 PNG 字符串。"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100)
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_base64


def call_deepseek_chat(prompt: str, api_key: str) -> str:
    """直接调用 DeepSeek API 的简单封装。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 500
    }
    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


# ---------- Celery 任务 ----------
@celery_app.task
def log_audit_task(user_id, tenant_id, action, details, ip, user_agent):
    """异步写入审计日志"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.audit import AuditLog
    sync_engine = create_engine(settings.DATABASE_URL.replace("mysql+aiomysql", "mysql+pymysql"))
    SessionLocal = sessionmaker(bind=sync_engine)
    db = SessionLocal()
    try:
        log_entry = AuditLog(
            user_id=user_id if isinstance(user_id, int) else None,
            tenant_id=tenant_id,
            action=action,
            details=json.dumps(details, ensure_ascii=False),
            ip_address=ip,
            user_agent=user_agent
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        logger.error(f"审计日志记录失败：{e}")
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def index_document_task(self, file_content: bytes, filename: str, metadata: dict):
    """异步处理文档索引任务"""
    try:
        docs = document_processor.load_document_sync(file_content, filename, metadata)
        chunk_count = rag_service.add_documents_sync(docs, metadata)
        logger.info(f"文档 {filename} 索引完成，共 {chunk_count} 个块")
        return {"status": "success", "filename": filename, "chunks": chunk_count}
    except Exception as e:
        logger.error(f"文档索引失败 {filename}: {e}")
        self.retry(exc=e, countdown=60)


@celery_app.task
def update_knowledge_base_from_db_task(table_name: str, filter_condition: dict = None):
    """从数据库增量同步数据到知识库（示例）"""
    pass


class CompetitorDataSchema(BaseModel):
    company_name: str = Field(description="Name of the company")
    pricing: str = Field(description="Pricing details, tiers, and plans")
    key_features: List[str] = Field(description="Main features and capabilities of the product/service")
    tech_stack: List[str] = Field(description="Technologies, frameworks, and tools used")
    marketing_focus: str = Field(description="Main marketing angles and target audience")
    customer_feedback: str = Field(description="Customer testimonials, reviews, and feedback")


def _fetch_competitor_urls(
    input_url: Optional[str],
    input_description: Optional[str],
    search_engine: str,
    perplexity_api_key: Optional[str],
    exa_api_key: Optional[str],
    deepseek_api_key: str,
) -> List[str]:
    if search_engine == "perplexity":
        return _fetch_urls_via_perplexity(input_url, input_description, perplexity_api_key)
    else:
        return _fetch_urls_via_exa(input_url, input_description, exa_api_key, deepseek_api_key)


def _fetch_urls_via_perplexity(url: Optional[str], description: Optional[str], api_key: str) -> List[str]:
    if not api_key:
        raise ValueError("未提供 Perplexity API Key")
    content = "Find me 3 competitor company URLs similar to the company with "
    if url and description:
        content += f"URL: {url} and description: {description}"
    elif url:
        content += f"URL: {url}"
    else:
        content += f"description: {description}"
    content += ". ONLY RESPOND WITH THE URLS, NO OTHER TEXT."
    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": "Be precise and only return 3 company URLs ONLY."},
            {"role": "user", "content": content}
        ],
        "max_tokens": 1000,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    urls_text = response.json()['choices'][0]['message']['content'].strip()
    return [line.strip() for line in urls_text.split('\n') if line.strip() and line.strip().startswith('http')][:3]


def _fetch_urls_via_exa(
    url: Optional[str], description: Optional[str], api_key: str, deepseek_key: str
) -> List[str]:
    if not api_key:
        raise ValueError("未提供 Exa API Key")
    exa_tools = ExaTools(api_key=api_key, category="company", num_results=3)
    model = OpenAILike(id="deepseek-chat", api_key=deepseek_key, base_url="https://api.deepseek.com/v1")
    agent = Agent(
        model=model,
        tools=[exa_tools],
        instructions=[
            "You are a competitor finder agent. Use ExaTools to find competitor company URLs.",
            "When given a URL, find similar companies. When given a description, search for companies matching that description.",
            "Return ONLY the URLs, one per line, with no additional text."
        ],
        markdown=False,
    )
    if url:
        prompt = f"Find 3 competitor company URLs similar to: {url}. Return ONLY the URLs, one per line."
    else:
        prompt = f"Find 3 competitor company URLs matching this description: {description}. Return ONLY the URLs, one per line."
    response = agent.run(prompt)
    lines = response.content.strip().split('\n')
    return [line.strip() for line in lines if line.strip() and line.strip().startswith('http')][:3]


def _extract_competitor_info(app: FirecrawlApp, competitor_url: str) -> Optional[Dict[str, Any]]:
    try:
        url_pattern = f"{competitor_url}/*"
        extraction_prompt = """
        Extract detailed information about the company's offerings, including:
        - Company name and basic information
        - Pricing details, plans, and tiers
        - Key features and main capabilities
        - Technology stack and technical details
        - Marketing focus and target audience
        - Customer feedback and testimonials
        Analyze the entire website content to provide comprehensive information for each field.
        """
        response = app.extract(
            [url_pattern],
            prompt=extraction_prompt,
            schema=CompetitorDataSchema.model_json_schema()
        )
        if hasattr(response, 'success') and response.success and hasattr(response, 'data') and response.data:
            data = response.data
            return {
                "competitor_url": competitor_url,
                "company_name": data.get('company_name', 'N/A') if isinstance(data, dict) else getattr(data, 'company_name', 'N/A'),
                "pricing": data.get('pricing', 'N/A') if isinstance(data, dict) else getattr(data, 'pricing', 'N/A'),
                "key_features": (data.get('key_features', [])[:5] if isinstance(data, dict) else getattr(data, 'key_features', [])[:5]) if data.get('key_features') else ['N/A'],
                "tech_stack": (data.get('tech_stack', [])[:5] if isinstance(data, dict) else getattr(data, 'tech_stack', [])[:5]) if data.get('tech_stack') else ['N/A'],
                "marketing_focus": data.get('marketing_focus', 'N/A') if isinstance(data, dict) else getattr(data, 'marketing_focus', 'N/A'),
                "customer_feedback": data.get('customer_feedback', 'N/A') if isinstance(data, dict) else getattr(data, 'customer_feedback', 'N/A')
            }
        return None
    except Exception as e:
        logger.error(f"Firecrawl 提取失败 {competitor_url}: {e}")
        return None


def _generate_analysis_report(api_key: str, competitor_data: List[Dict]) -> str:
    model = OpenAILike(id="deepseek-chat", api_key=api_key, base_url="https://api.deepseek.com/v1")
    agent = Agent(model=model, markdown=True)
    formatted_data = json.dumps(competitor_data, indent=2, ensure_ascii=False)
    prompt = f"""
    Analyze the following competitor data in JSON format and identify market opportunities to improve my own company:

    {formatted_data}

    Tasks:
    1. Identify market gaps and opportunities based on competitor offerings
    2. Analyze competitor weaknesses that we can capitalize on
    3. Recommend unique features or capabilities we should develop
    4. Suggest pricing and positioning strategies to gain competitive advantage
    5. Outline specific growth opportunities in underserved market segments
    6. Provide actionable recommendations for product development and go-to-market strategy

    Focus on finding opportunities where we can differentiate and do better than competitors.
    Highlight any unmet customer needs or pain points we can address.
    """
    response = agent.run(prompt)
    return response.content


def _sync_update_task(task_id: int, status: AnalysisStatus, message: str = None, **kwargs):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    sync_engine = create_engine(settings.DATABASE_URL.replace("mysql+aiomysql", "mysql+pymysql"))
    SessionLocal = sessionmaker(bind=sync_engine)
    db = SessionLocal()
    try:
        stmt = update(CompetitorAnalysisTask).where(CompetitorAnalysisTask.id == task_id)
        values = {"status": status}
        if message:
            values["progress_message"] = message
        values.update(kwargs)
        db.execute(stmt.values(**values))
        db.commit()
    except Exception as e:
        logger.error(f"更新任务状态失败: {e}")
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2)
def run_competitor_analysis(
    self,
    task_id: int,
    deepseek_api_key: str,
    firecrawl_api_key: str,
    search_engine: str,
    perplexity_api_key: Optional[str] = None,
    exa_api_key: Optional[str] = None,
):
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        sync_engine = create_engine(settings.DATABASE_URL.replace("mysql+aiomysql", "mysql+pymysql"))
        SessionLocal = sessionmaker(bind=sync_engine)
        db = SessionLocal()
        task = db.query(CompetitorAnalysisTask).filter(CompetitorAnalysisTask.id == task_id).first()
        db.close()
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")
        input_url = task.input_url
        input_description = task.input_description
        _sync_update_task(task_id, AnalysisStatus.FETCHING_URLS, "正在搜索竞品网站...")
        competitor_urls = _fetch_competitor_urls(
            input_url, input_description, search_engine,
            perplexity_api_key, exa_api_key, deepseek_api_key
        )
        if not competitor_urls:
            raise ValueError("未找到任何竞品 URL")
        _sync_update_task(task_id, AnalysisStatus.CRAWLING, f"发现 {len(competitor_urls)} 个竞品，正在提取数据...",
                          competitor_urls=competitor_urls)
        app = FirecrawlApp(api_key=firecrawl_api_key)
        extracted_data = []
        for idx, url in enumerate(competitor_urls):
            _sync_update_task(task_id, AnalysisStatus.CRAWLING, f"正在分析竞品 {idx+1}/{len(competitor_urls)}: {url}")
            info = _extract_competitor_info(app, url)
            if info:
                extracted_data.append(info)
        if not extracted_data:
            raise ValueError("所有竞品网站数据提取失败")
        _sync_update_task(task_id, AnalysisStatus.ANALYZING, "正在生成分析报告...", extracted_data=extracted_data)
        report = _generate_analysis_report(deepseek_api_key, extracted_data)
        _sync_update_task(task_id, AnalysisStatus.COMPLETED, "分析完成", analysis_report=report)
        return {"status": "success", "task_id": task_id}
    except Exception as e:
        logger.exception(f"竞品分析任务 {task_id} 失败")
        _sync_update_task(task_id, AnalysisStatus.FAILED, error_detail=str(e))
        self.retry(exc=e, countdown=60)


# ---------- 数据分析任务 ----------
def _generate_pandas_code(query: str, sample_data: str, api_key: str) -> str:
    model = OpenAILike(id="deepseek-chat", api_key=api_key, base_url="https://api.deepseek.com/v1")
    agent = Agent(model=model, markdown=False)
    prompt = f"""
        You are a pandas expert. Given a user query and a sample of the DataFrame, write pandas code to answer the query.

        Sample Data (first 5 rows):
        {sample_data}

        User Query: {query}

        Requirements:
        - The DataFrame is already loaded as `df`.
        - If the query asks for multiple separate analyses (e.g., "trend over time" and "comparison by category"), **return each analysis as a separate DataFrame** in a dictionary named `result_dict`.
        - The keys of `result_dict` should be descriptive names (e.g., 'monthly_trend', 'category_comparison').
        - Do NOT merge results together unless the query explicitly asks for a single combined view.
        - Write only valid pandas code, no explanations.
        - Ensure the code handles potential missing values.

        Example output format:
        ```python
        monthly_trend = df.groupby('Month')['Sales'].sum().reset_index()
        category_comparison = df.groupby('Category')['Sales'].sum().reset_index()
        result_dict = {{'monthly_trend': monthly_trend, 'category_comparison': category_comparison}}
    """
    response = agent.run(prompt)
    code = response.content.strip()
    # 移除 Markdown 代码块标记
    code = re.sub(r'^```python\s*', '', code, flags=re.IGNORECASE)
    code = re.sub(r'\s*```$', '', code)

    # 移除 UTF-8 BOM 头
    code = code.lstrip('\ufeff')

    # 去除第一行缩进（若 LLM 不小心加了缩进）
    lines = code.splitlines()
    if lines:
        # 计算第一行前导空格数量
        leading_spaces = len(lines[0]) - len(lines[0].lstrip(' '))
        if leading_spaces > 0:
            # 将每行统一左移 leading_spaces 个空格
            lines = [line[leading_spaces:] if line.startswith(' ' * leading_spaces) else line for line in lines]
            code = '\n'.join(lines)

    logger.debug(f"清洗后代码开头 repr: {repr(code[:20])}")
    return code.strip()


def _store_analysis_to_kb(
        query_task_id: int,
        query: str,
        execution_result: Dict[str, Any],
        tenant_id: int,
        chart_count: int
):
    """将分析结果摘要存入 RAG 知识库（同步调用）"""
    from langchain_core.documents import Document
    from app.services.rag_service import rag_service
    import json
    from datetime import datetime, timezone

    # 构建摘要文本
    summary_lines = [f"分析查询：{query}"]
    for key, records in execution_result.items():
        if records:
            summary_lines.append(
                f"结果集「{key}」包含 {len(records)} 行，"
                f"样例：{json.dumps(records[:3], ensure_ascii=False)}"
            )
    summary_text = "\n".join(summary_lines)

    # 构建元数据
    safe_metadata = {
        "source": f"analysis_result_{query_task_id}",
        "query_task_id": query_task_id,
        "tenant_id": tenant_id,
        "type": "analysis_result",
        "query": query,
        "chart_count": chart_count,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "result_keys": json.dumps(list(execution_result.keys()), ensure_ascii=False)
    }

    doc = Document(page_content=summary_text, metadata=safe_metadata)

    if not rag_service.is_ready:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(rag_service.initialize())
        loop.close()

        # 🔁 加载最新的 BM25 索引，确保不会复活已删除文档
    rag_service.bm25_retriever.load(str(rag_service.bm25_index_path))

    # ✅ 加载最新BM25索引，防止复活已删除文档
    rag_service.bm25_retriever.load(str(rag_service.bm25_index_path))

    # 分块：分析摘要通常较短，保留完整语义
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    if len(doc.page_content) <= 1000:
        chunks = [doc]
    else:
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=100,
            separators=["\n## ", "\n### ", "\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
        )
        chunks = text_splitter.split_documents([doc])
        if not chunks:
            chunks = [doc]

    # 写入
    rag_service.vectorstore.add_documents(chunks)
    rag_service.bm25_retriever.add_documents(chunks)
    rag_service.bm25_retriever.save(str(rag_service.bm25_index_path))

    logger.info(f"分析结果已存入知识库，任务ID {query_task_id}，块数：{len(chunks)}")

def _execute_pandas_code(code: str, df: pd.DataFrame) -> Tuple[pd.DataFrame, str, str]:
    """在受限命名空间中执行代码，返回 (结果DataFrame, 错误类型, 错误详情)"""
    namespace = {"df": df, "pd": pd}
    try:
        exec(code, namespace)
        result = namespace.get("result_df")
        if result is None:
            return pd.DataFrame({"信息": ["代码执行成功，但未返回结果"]}), "", ""
        if isinstance(result, (int, float, str, dict)):
            return pd.DataFrame([result]), "", ""
        if isinstance(result, pd.Series):
            return result.to_frame(), "", ""
        if isinstance(result, pd.DataFrame):
            return result, "", ""
        return pd.DataFrame(result), "", ""
    except SyntaxError as e:
        error_detail = f"语法错误 at line {e.lineno}, column {e.offset}: {e.msg}"
        return pd.DataFrame({"错误": [error_detail]}), "syntax_error", error_detail
    except NameError as e:
        error_detail = f"变量未定义: {e}"
        return pd.DataFrame({"错误": [error_detail]}), "name_error", error_detail
    except KeyError as e:
        error_detail = f"列名不存在: {e}"
        return pd.DataFrame({"错误": [error_detail]}), "key_error", error_detail
    except Exception as e:
        error_detail = f"执行错误: {e}"
        return pd.DataFrame({"错误": [error_detail]}), "runtime_error", error_detail


def _generate_charts(result_df: pd.DataFrame, query: str, api_key: str) -> List[Dict[str, Any]]:
    if result_df.empty:
        return []

    # 识别 DataFrame 中的数值列和分类列，供 LLM 参考
    num_cols = result_df.select_dtypes(include=['number']).columns.tolist()
    cat_cols = result_df.select_dtypes(include=['object', 'category']).columns.tolist()
    all_cols = result_df.columns.tolist()

    # 如果只有一列数值，提示 LLM 不要推荐多张图
    max_charts = 1 if len(num_cols) <= 1 and len(cat_cols) == 0 else 3

    prompt = f"""
你是一个数据可视化专家。根据以下数据分析结果和用户查询，推荐**最多{max_charts}张**最能揭示数据洞察的图表。

用户查询：{query}

数据结果（前5行）：
{result_df.head(5).to_string()}

列名及类型：
{result_df.dtypes.to_string()}

可用的数值列：{num_cols}
可用的分类列：{cat_cols}

请返回一个 JSON 数组，每个元素是一个图表配置对象。**重要要求**：
- 如果数据维度单一（只有一组数值），只返回 **1张** 最合适的图表，不要重复推荐。
- 如果数据包含多个维度（如同时有时间和类别），可以针对不同维度推荐不同图表（如时间趋势用折线图，类别对比用柱状图）。
- 图表配置格式：
  {{
      "chart_type": "bar|line|scatter|pie",
      "x_column": "列名（如果使用索引则写 'index'）",
      "y_column": "数值列名",
      "title": "图表标题"
  }}

只返回 JSON 数组，不要包含任何其他文字。如果没有合适的图表，返回空数组 []。
"""
    llm_response = call_deepseek_chat(prompt, api_key)
    logger.info(f"LLM 多图原始响应: {llm_response}")

    charts_config = []
    try:
        cleaned = clean_llm_json_response(llm_response)
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            charts_config = parsed
        elif isinstance(parsed, dict):
            charts_config = [parsed]
    except Exception as e:
        logger.warning(f"LLM 多图推荐解析失败，使用降级配置: {e}")
        charts_config = [fallback_chart_params(result_df)]

    # 去重：如果多个图表配置完全相同，只保留一个
    unique_configs = []
    seen = set()
    for cfg in charts_config:
        key = (cfg.get("chart_type"), cfg.get("x_column"), cfg.get("y_column"))
        if key not in seen:
            seen.add(key)
            unique_configs.append(cfg)

    charts = []
    for cfg in unique_configs:
        try:
            chart_type = cfg.get("chart_type", "bar")
            x_col = cfg.get("x_column")
            y_col = cfg.get("y_column")
            title = cfg.get("title", "数据可视化")

            if not x_col or not y_col:
                continue

            # 验证列是否存在，若不存在则尝试智能修正
            if y_col not in result_df.columns:
                logger.warning(f"LLM 推荐的 y_column '{y_col}' 不存在，尝试从数值列中选择")
                if num_cols:
                    y_col = num_cols[0]
                    cfg["y_column"] = y_col
                else:
                    continue
            if x_col not in result_df.columns and x_col != 'index':
                logger.warning(f"LLM 推荐的 x_column '{x_col}' 不存在，尝试使用索引或第一列")
                x_col = 'index'
                cfg["x_column"] = 'index'

            plot_df = validate_and_prepare_data(result_df, x_col, y_col, chart_type)
            fig = draw_chart(plot_df, chart_type, x_col, y_col, title)
            img_base64 = fig_to_base64(fig)

            charts.append({
                "config": cfg,
                "chart_type": chart_type,
                "title": title,
                "image_base64": img_base64
            })
            logger.info(f"成功生成图表: {title} ({chart_type})")
        except Exception as e:
            logger.error(f"单张图表生成失败: {e}, 配置: {cfg}")

    return charts


from langchain_community.vectorstores.utils import filter_complex_metadata


@celery_app.task(bind=True, max_retries=3)
def index_document_task(self, file_content: bytes, filename: str, metadata: dict):
    """异步处理文档索引任务（同步写入版本）"""
    try:
        # 1. 加载文档
        docs = document_processor.load_document_sync(file_content, filename, metadata)
        if not docs:
            logger.warning(f"文档 {filename} 未提取到任何内容")
            return {"status": "skipped", "filename": filename, "chunks": 0}

        logger.info(f"文档 {filename} 解析得到 {len(docs)} 个原始文档对象")

        # 2. 确保 RAG 服务已初始化（若未初始化，同步执行）
        if not rag_service.is_ready:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(rag_service.initialize())
            loop.close()
            logger.info("RAG服务已在Worker中初始化")

        # 3. 完善元数据
        full_metadata = metadata.copy()
        # 推断文件类型
        ext = os.path.splitext(filename)[1].lower()
        file_type_map = {
            '.csv': 'csv', '.xlsx': 'excel', '.xls': 'excel',
            '.pdf': 'pdf', '.txt': 'text', '.md': 'markdown',
            '.docx': 'docx'
        }
        full_metadata['file_type'] = file_type_map.get(ext, 'unknown')
        full_metadata['source'] = filename

        for doc in docs:
            doc.metadata.update(full_metadata)
            if "id" not in doc.metadata:
                doc.metadata["id"] = str(uuid.uuid4())
            doc.metadata["indexed_at"] = datetime.now(timezone.utc).isoformat()

        # 4. 分块（与 add_documents 保持一致）
        if full_metadata.get("file_type") in ["csv", "excel"]:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=700,
                chunk_overlap=0,
                separators=["\n"]
            )
        else:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000,
                chunk_overlap=100,
                separators=["\n## ", "\n### ", "\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
            )
        chunks = text_splitter.split_documents(docs)
        logger.info(f"分块完成，得到 {len(chunks)} 个块")

        if not chunks:
            logger.warning(f"文档 {filename} 分块后无内容")
            return {"status": "skipped", "filename": filename, "chunks": 0}

        # 5. 直接同步写入向量库和 BM25（绕过异步）
        rag_service.vectorstore.add_documents(chunks)
        rag_service.bm25_retriever.add_documents(chunks)
        rag_service.bm25_retriever.save(str(rag_service.bm25_index_path))

        logger.info(f"文档 {filename} 索引完成，共 {len(chunks)} 个块")
        return {"status": "success", "filename": filename, "chunks": len(chunks)}

    except Exception as e:
        logger.exception(f"文档索引失败 {filename}: {e}")
        self.retry(exc=e, countdown=60)

@celery_app.task(bind=True, max_retries=1)
def execute_data_analysis(
    self,
    query_task_id: int,
    query: str,
    deepseek_api_key: str,
    save_to_kb: bool = False,
    tenant_id: Optional[int] = None
):
    import matplotlib
    matplotlib.use('Agg')
    import math
    import json

    from sqlalchemy.orm import sessionmaker
    from app.models.data_analysis import DataAnalysisTask
    from app.models.query_task import QueryTask
    from app.models.analysis_chart import AnalysisChart

    sync_engine = create_engine(settings.DATABASE_URL.replace("mysql+aiomysql", "mysql+pymysql"))
    SessionLocal = sessionmaker(bind=sync_engine)
    db = SessionLocal()
    try:
        query_task = db.query(QueryTask).filter(QueryTask.id == query_task_id).first()
        if not query_task:
            raise ValueError("查询任务不存在")

        query_task.status = "running"
        db.commit()

        analysis_task = db.query(DataAnalysisTask).filter(DataAnalysisTask.id == query_task.analysis_task_id).first()
        if not analysis_task:
            raise ValueError("关联的文件任务不存在")

        # 加载数据
        if analysis_task.table_name:
            df = pd.read_sql(f"SELECT * FROM {analysis_task.table_name}", sync_engine)
        else:
            if analysis_task.filename.endswith('.csv'):
                df = pd.read_csv(analysis_task.file_path)
            else:
                df = pd.read_excel(analysis_task.file_path)

        # 生成代码（优化后的提示词）
        code = _generate_pandas_code(query, df.head(5).to_string(), deepseek_api_key)
        query_task.generated_code = code
        db.commit()

        # 执行代码
        namespace = {"df": df, "pd": pd}
        try:
            exec(code, namespace)
        except Exception as e:
            # 执行错误处理
            error_type = "runtime_error"
            error_detail = str(e)
            query_task.status = "failed"
            query_task.error_type = error_type
            query_task.error_detail = error_detail
            db.commit()
            return {"status": "failed", "query_task_id": query_task_id, "error_type": error_type}

        # 检查是否返回了字典格式的多结果
        result_dict = namespace.get("result_dict")
        if result_dict is None:
            # 兼容旧版单 DataFrame 格式
            result_df = namespace.get("result_df")
            if result_df is None:
                result_df = pd.DataFrame({"信息": ["代码执行成功，但未返回结果"]})
            result_dict = {"default": result_df}

        # 验证 result_dict 中的每个值都是 DataFrame
        cleaned_results = {}
        for key, value in result_dict.items():
            if not isinstance(value, pd.DataFrame):
                if isinstance(value, (pd.Series, list, dict)):
                    value = pd.DataFrame(value)
                else:
                    value = pd.DataFrame({key: [value]})
            cleaned_results[key] = value

        # 为每个子结果生成图表
        all_charts = []
        for key, sub_df in cleaned_results.items():
            if not sub_df.empty:
                try:
                    charts = _generate_charts(sub_df, f"{query} - {key}", deepseek_api_key)
                    for chart in charts:
                        chart["result_key"] = key  # 标记属于哪个子结果
                    all_charts.extend(charts)
                except Exception as e:
                    logger.error(f"为 '{key}' 生成图表失败: {e}")

        # 保存所有图表
        for chart in all_charts:
            # 压缩 Base64 长度（可选，降低存储压力）
            img_data = chart["image_base64"]
            if len(img_data) > 100000:  # 如果仍然过长，可考虑压缩或降采样
                logger.warning(f"图表 Base64 长度 {len(img_data)}，可能超出数据库限制")
            chart_record = AnalysisChart(
                query_task_id=query_task.id,
                chart_type=chart.get("chart_type"),
                title=chart.get("title"),
                config=chart.get("config"),
                image_base64=img_data
            )
            db.add(chart_record)

        # 清洗并保存多结果
        def deep_clean(obj):
            if isinstance(obj, dict):
                return {k: deep_clean(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [deep_clean(v) for v in obj]
            elif isinstance(obj, pd.DataFrame):
                return deep_clean(obj.to_dict(orient='records'))
            elif isinstance(obj, pd.Series):
                return deep_clean(obj.to_dict())
            elif isinstance(obj, float):
                if math.isnan(obj) or math.isinf(obj):
                    return None
                return obj
            elif isinstance(obj, (int, str, bool)) or obj is None:
                return obj
            else:
                return str(obj)

        final_results = {}
        for key, sub_df in cleaned_results.items():
            records = sub_df.head(100).to_dict(orient='records')
            final_results[key] = deep_clean(records)

        try:
            json.dumps(final_results)
        except Exception as e:
            logger.error(f"清洗后数据仍不可序列化: {e}")
            final_results = {"error": "数据包含无法序列化的对象"}

        query_task.execution_result = final_results
        query_task.status = "completed"

        # ✅ 存储到知识库（如果用户选择）
        if save_to_kb and tenant_id:
            try:
                _store_analysis_to_kb(
                    query_task_id=query_task.id,
                    query=query,
                    execution_result=final_results,
                    tenant_id=tenant_id,
                    chart_count=len(all_charts)
                )
            except Exception as e:
                logger.error(f"知识库存储失败（任务 {query_task_id}）：{e}")

        db.commit()
        return {"status": "completed", "query_task_id": query_task_id}

    except Exception as e:
        logger.exception(f"数据分析查询任务 {query_task_id} 失败")
        db.rollback()
        query_task.status = "failed"
        query_task.error_detail = str(e)
        db.commit()
        raise
    finally:
        db.close()