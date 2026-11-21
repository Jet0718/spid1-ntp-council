"""摘要紀錄與審查會會議紀錄 PDF 解析器。

職責：把 PDF 轉成文字，並切出「標題、出席、請假」欄位與全文。
姓名與名冊的對應交給 CouncilorRegistry，本模組不處理（單一職責原則）。
PDF 文字擷取透過 IPdfTextExtractor 介面注入，可替換為其他引擎（依賴反轉原則）。
"""
from __future__ import annotations

import io
import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional

from .models import PdfParseResult

logger = logging.getLogger(__name__)


def _label(word: str) -> str:
    """把欄位名稱轉成允許字間空白的正規表示式，例如「出席」→「出\\s*席」。"""
    return r"\s*".join(map(re.escape, word))


# 出席欄位：「出  席：」「出席委員：」「出席議員：」
_ATTEND_RE = re.compile(rf"{_label('出席')}(?:\s*(?:委\s*員|議\s*員))?\s*[：:]")
# 請假欄位
_LEAVE_RE = re.compile(rf"{_label('請假')}(?:\s*(?:委\s*員|議\s*員))?\s*[：:]")
# 欄位結束標記：遇到下一個表頭欄位即停止
_FIELD_END_RE = re.compile(
    "(?:" + "|".join(_label(w) for w in ("出席", "請假", "列席", "主席", "記錄", "紀錄", "缺席", "時間", "地點"))
    + r")(?:\s*(?:委\s*員|議\s*員))?\s*[：:]"
)
# 頁碼列，例如「第1/2頁」
_PAGE_NO_RE = re.compile(r"^第\s*\d+\s*/\s*\d+\s*頁$")


class IPdfTextExtractor(ABC):
    """PDF 文字擷取介面。"""

    @abstractmethod
    def extract(self, pdf_bytes: bytes) -> str:
        """回傳 PDF 全部頁面的文字。"""


class PypdfTextExtractor(IPdfTextExtractor):
    """以 pypdf 實作的文字擷取器。"""

    def extract(self, pdf_bytes: bytes) -> str:
        """擷取全部頁面文字；檔案損毀時回傳空字串。"""
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(pdf_bytes))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # pypdf 對損毀檔可能拋出多種例外
            logger.warning("PDF 文字擷取失敗：%s", exc)
            return ""


class PdfRecordParser:
    """摘要紀錄 / 審查會會議紀錄 PDF 解析器。"""

    def __init__(self, extractor: Optional[IPdfTextExtractor] = None) -> None:
        """建立解析器。

        Args:
            extractor: PDF 文字擷取器，預設使用 pypdf
        """
        self._extractor = extractor or PypdfTextExtractor()

    def parse_bytes(self, pdf_bytes: bytes) -> PdfParseResult:
        """解析 PDF 位元組。"""
        return self.parse_text(self._extractor.extract(pdf_bytes))

    @staticmethod
    def _extract_field(text: str, start_re: re.Pattern) -> Optional[str]:
        """取出指定欄位內容（至下一個表頭欄位為止）。"""
        m = start_re.search(text)
        if not m:
            return None
        rest = text[m.end():]
        end = _FIELD_END_RE.search(rest)
        return (rest[: end.start()] if end else rest[:800]).strip()

    @staticmethod
    def _extract_title(text: str) -> str:
        """取出文件標題（第一個含「紀錄／記錄」的列，最多合併前 3 列）。"""
        lines: List[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or _PAGE_NO_RE.match(line):
                continue
            lines.append(line)
            if "紀錄" in line or "記錄" in line or len(lines) >= 3:
                break
        return re.sub(r"\s+", "", "".join(lines))

    def parse_text(self, text: str) -> PdfParseResult:
        """解析 PDF 文字。

        Args:
            text: PDF 全文
        Returns:
            PdfParseResult（姓名尚未對應名冊）
        """
        result = PdfParseResult()
        result.has_text = len(re.sub(r"\s+", "", text)) > 20
        if not result.has_text:
            return result
        result.full_text = text
        result.title = self._extract_title(text)
        result.attend_raw = self._extract_field(text, _ATTEND_RE)
        result.leave_raw = self._extract_field(text, _LEAVE_RE)
        result.sign_in_book = bool(result.attend_raw and "簽到" in result.attend_raw)
        return result
