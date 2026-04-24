# app/services/sensitive_filter.py
import ahocorasick_rs
from app.core.config import settings
import aiofiles
from pathlib import Path

class SensitiveFilter:
    _instance = None
    _automaton = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_automaton()
        return cls._instance

    def _init_automaton(self):
        word_path = Path(settings.SENSITIVE_WORDS_FILE)
        if not word_path.exists():
            # 若文件不存在，创建一个空文件
            word_path.touch()
        with open(word_path, "r", encoding="utf-8") as f:
            words = [line.strip() for line in f if line.strip()]
        self._automaton = ahocorasick_rs.AhoCorasick(words)

    def contains_sensitive(self, text: str) -> bool:
        """检查文本是否包含敏感词"""
        return len(self._automaton.find_matches_as_strings(text)) > 0

    def filter_text(self, text: str, replace_char: str = "*") -> str:
        """将敏感词替换为指定字符"""
        matches = self._automaton.find_matches_as_strings(text)
        for m in matches:
            text = text.replace(m, replace_char * len(m))
        return text

    async def reload_words(self):
        """热更新敏感词库（异步）"""
        self._init_automaton()

sensitive_filter = SensitiveFilter()