# app/services/answer_validator.py
import re
import json
from typing import List, Tuple, Optional, Dict, Any
from app.services.sensitive_filter import sensitive_filter
from app.core.logger import get_logger

logger = get_logger(__name__)


class AnswerValidator:
    """LLM 输出校验器：敏感词、数字、价格/库存模拟校验、合规承诺检测"""

    def __init__(self):
        # 价格/库存模拟数据（实际应调用真实 API）
        self.mock_product_db = {
            "SKU001": {"price": 199.00, "stock": 50, "name": "无线降噪耳机"},
            "SKU002": {"price": 89.90, "stock": 0, "name": "运动手环"},
            "SKU003": {"price": 2999.00, "stock": 12, "name": "智能投影仪"},
        }

        # 电商常见数字字段及其合理范围
        self.number_patterns = {
            "price": {
                "pattern": r"(?:价格|售价|单价|原价|现价)[：:]\s*(\d+(?:\.\d{1,2})?)\s*元",
                "min": 0.01,
                "max": 100000.0,
                "unit": "元"
            },
            "weight": {
                "pattern": r"(?:重量|净重|毛重)[：:]\s*(\d+(?:\.\d{1,2})?)\s*(克|g|千克|kg|公斤)",
                "min": 0.01,
                "max": 1000.0,
                "unit_conversion": {"克": 1, "g": 1, "千克": 1000, "kg": 1000, "公斤": 1000}
            },
            "size": {
                "pattern": r"(?:尺寸|规格|长|宽|高)[：:]\s*(\d+(?:\.\d{1,2})?)\s*(厘米|cm|毫米|mm|米|m)",
                "min": 0.1,
                "max": 1000.0,
                "unit_conversion": {"厘米": 1, "cm": 1, "毫米": 0.1, "mm": 0.1, "米": 100, "m": 100}
            },
            "stock": {
                "pattern": r"(?:库存|存货|剩余)[：:]\s*(\d+)\s*件",
                "min": 0,
                "max": 999999,
                "unit": "件"
            }
        }

        # 过度承诺用语黑名单（正则表达式）
        self.commitment_patterns = [
            (r"假一赔[十百千万\d]+", "过度承诺：假一赔N"),
            (r"绝对安全", "过度承诺：绝对安全"),
            (r"100%有效", "过度承诺：100%有效"),
            (r"永不损坏", "过度承诺：永不损坏"),
            (r"无条件退款", "过度承诺：无条件退款"),
            (r"终身保修", "过度承诺：终身保修"),
            (r"全网最低价", "过度承诺：全网最低价"),
            (r"最便宜", "过度承诺：最便宜"),
            (r"保证\d+天送达", "过度承诺：保证送达时效"),
        ]

    def filter_sensitive_output(self, text: str) -> Tuple[str, bool]:
        """输出敏感词过滤"""
        if sensitive_filter.contains_sensitive(text):
            filtered = sensitive_filter.filter_text(text)
            logger.warning("LLM 输出包含敏感词，已过滤")
            return filtered, True
        return text, False

    def validate_numbers(self, text: str, context: Dict[str, Any] = None) -> Tuple[str, List[Dict]]:
        """
        对输出中的数字进行校验与修正
        返回 (修正后文本, 修正记录列表)
        """
        corrections = []
        for field_name, config in self.number_patterns.items():
            pattern = config["pattern"]
            for match in re.finditer(pattern, text):
                original = match.group(0)
                value = float(match.group(1))
                unit = match.group(2) if len(match.groups()) > 1 else config.get("unit", "")

                # 单位换算（如克转千克）
                if "unit_conversion" in config and unit in config["unit_conversion"]:
                    value = value * config["unit_conversion"][unit]
                    # 统一单位显示（可选）

                min_val = config.get("min", 0)
                max_val = config.get("max", float("inf"))

                if value < min_val or value > max_val:
                    # 修正为合理范围
                    corrected_value = max(min_val, min(value, max_val))
                    corrected_str = re.sub(r"\d+(?:\.\d+)?", str(corrected_value), original, count=1)
                    text = text.replace(original, corrected_str)
                    corrections.append({
                        "field": field_name,
                        "original": original,
                        "corrected": corrected_str,
                        "reason": f"数值超出合理范围 [{min_val}, {max_val}]"
                    })
                    logger.warning(f"数字校验修正: {original} -> {corrected_str}")
        return text, corrections

    def detect_commitments(self, text: str) -> Tuple[str, List[Dict]]:
        """
        检测并移除过度承诺用语
        返回 (修正后文本, 检测到的承诺列表)
        """
        detected = []
        for pattern, description in self.commitment_patterns:
            if re.search(pattern, text):
                detected.append({"pattern": pattern, "description": description})
                # 替换为警告占位符
                text = re.sub(pattern, "[承诺用语已移除]", text)
                logger.warning(f"检测到过度承诺: {description}")
        return text, detected

    async def check_price_stock(self, user_query: str) -> Optional[str]:
        """价格/库存实时数据注入（保持不变）"""
        query_lower = user_query.lower()
        if "价格" in query_lower or "多少钱" in query_lower or "price" in query_lower:
            for sku, info in self.mock_product_db.items():
                if sku.lower() in query_lower or info["name"].lower() in query_lower:
                    return f"[实时数据] 商品 {info['name']} (SKU: {sku}) 当前价格：{info['price']} 元"
            return "[实时数据] 请提供具体商品名称或SKU，以便查询准确价格。"
        elif "库存" in query_lower or "有没有货" in query_lower or "stock" in query_lower:
            for sku, info in self.mock_product_db.items():
                if sku.lower() in query_lower or info["name"].lower() in query_lower:
                    stock_status = "有货" if info["stock"] > 0 else "无货"
                    return f"[实时数据] 商品 {info['name']} (SKU: {sku}) 当前库存：{info['stock']} 件 ({stock_status})"
            return "[实时数据] 请提供具体商品名称或SKU，以便查询库存。"
        return None

    def validate_and_correct(self, answer: str, user_query: str = "", context: Dict = None) -> Tuple[str, Dict]:
        """
        综合校验入口
        返回 (修正后答案, 校验元数据)
        """
        meta = {
            "sensitive_hit": False,
            "price_stock_injected": False,
            "numbers_corrected": [],
            "commitments_detected": [],
        }

        # 1. 合规承诺检测（最先执行，防止敏感词干扰）
        answer, commitments = self.detect_commitments(answer)
        meta["commitments_detected"] = commitments

        # 2. 输出敏感词过滤
        filtered_answer, sensitive_hit = self.filter_sensitive_output(answer)
        meta["sensitive_hit"] = sensitive_hit
        answer = filtered_answer

        # 3. 数字校验
        answer, corrections = self.validate_numbers(answer, context)
        meta["numbers_corrected"] = corrections

        return answer, meta


answer_validator = AnswerValidator()