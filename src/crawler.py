"""議事錄網站爬蟲與本地快取管理模組。

結構：
- IFetcher：下載介面（依賴反轉，測試時可注入假資料）。
- HttpFetcher：實際 HTTPS 下載，含本地檔案快取、重試。
- AgendaPageParser：純函式解析總網頁、日程表、審查會紀錄清單頁（易於單元測試）。
- NtpCouncilCrawler：組合上述元件，提供高階檢索方法。
"""
from __future__ import annotations

import hashlib
import logging
import re
import ssl
import time
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .models import AgendaRow, AnnexPdfLink, ExamRecordLink, SessionInfo

logger = logging.getLogger(__name__)

BASE_URL = "https://ntpbook.ntp.gov.tw"  # 議事錄系統根網址
INDEX_URL = BASE_URL + "/Home/Home/IndexByMJ"  # 會期總網頁
_DATE_RE = re.compile(r"^\d{2,3}-\d{2}-\d{2}$")  # 民國日期，例如 115-08-05


class IFetcher(ABC):
    """網頁 / 檔案下載介面。"""

    @abstractmethod
    def fetch_bytes(self, url: str) -> bytes:
        """下載並回傳原始位元組。"""

    def fetch_text(self, url: str) -> str:
        """下載並以 UTF-8 解碼為文字。"""
        return self.fetch_bytes(url).decode("utf-8", errors="replace")


def build_ssl_context() -> ssl.SSLContext:
    """建立 SSL 連線設定。

    目標網站憑證缺少 Subject Key Identifier，Python 3.13+ 預設的 X.509 嚴格模式會拒絕。
    此處僅關閉 VERIFY_X509_STRICT 旗標，憑證鏈與主機名稱驗證仍維持開啟。
    """
    ctx = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


class HttpFetcher(IFetcher):
    """具本地快取與重試機制的 HTTPS 下載器。"""

    def __init__(self, cache_dir: Optional[Path] = Path(".cache"), retries: int = 3,
                 timeout: int = 60, use_cache: bool = True) -> None:
        """建立下載器。

        Args:
            cache_dir: 快取目錄；None 表示不快取
            retries: 失敗重試次數
            timeout: 單次請求逾時秒數
            use_cache: 是否讀取既有快取
        """
        self._cache_dir = cache_dir
        self._retries = retries
        self._timeout = timeout
        self._use_cache = use_cache
        self._ctx = build_ssl_context()
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url: str) -> Optional[Path]:
        """以網址 SHA1 作為快取檔名。"""
        if not self._cache_dir:
            return None
        return self._cache_dir / hashlib.sha1(url.encode("utf-8")).hexdigest()

    def fetch_bytes(self, url: str) -> bytes:
        """下載網址內容；有快取時直接讀快取，失敗則以指數退避重試。"""
        path = self._cache_path(url)
        if path and self._use_cache and path.exists():
            return path.read_bytes()
        last_err: Optional[Exception] = None
        for attempt in range(self._retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (council-stats)"})
                with urllib.request.urlopen(req, context=self._ctx, timeout=self._timeout) as resp:
                    data = resp.read()
                if path:
                    path.write_bytes(data)
                return data
            except Exception as exc:  # 網路錯誤種類多，統一重試
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"下載失敗：{url}（{last_err}）")


class AgendaPageParser:
    """議事錄網站各頁面的 HTML 解析（純函式，無網路存取）。"""

    @staticmethod
    def parse_index(html_text: str, term_prefix: str = "第4屆") -> List[SessionInfo]:
        """解析會期總網頁，取得指定屆次的會期清單。"""
        soup = BeautifulSoup(html_text, "html.parser")
        sessions: List[SessionInfo] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "BookAgenda?cBookMdslID=" not in href:
                continue
            name = "".join(a.get_text().split())
            if not name.startswith(term_prefix):
                continue
            sid = parse_qs(urlparse(href).query).get("cBookMdslID", [""])[0]
            if sid in seen:
                continue
            seen.add(sid)
            sessions.append(SessionInfo(sid, name, urljoin(BASE_URL, href)))
        return sessions

    @staticmethod
    def _cell_text(td) -> str:
        """取得儲存格文字並壓縮空白。"""
        return re.sub(r"\s+", " ", td.get_text(" ")).strip()

    @classmethod
    def parse_agenda(cls, html_text: str) -> List[AgendaRow]:
        """解析會期日程表，每一天回傳一個 AgendaRow。"""
        soup = BeautifulSoup(html_text, "html.parser")
        rows: List[AgendaRow] = []
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 5:
                continue
            date_str = cls._cell_text(tds[0])
            if not _DATE_RE.match(date_str):
                continue
            row = AgendaRow(date_str=date_str, order=cls._cell_text(tds[2]),
                            am_agenda=cls._cell_text(tds[3]), pm_agenda=cls._cell_text(tds[4]))
            seen_exam = set()
            for a in tr.find_all("a", href=True):
                href = urljoin(BASE_URL, a["href"])
                text = "".join(a.get_text().split())
                if href.lower().endswith(".pdf") and text.startswith("摘要紀錄"):
                    row.summary_pdf_url = row.summary_pdf_url or href
                elif "/BookAgenda/ViewRecord?" in href:
                    row.record_url = row.record_url or href
                elif "/BookAgenda/ViewExamAnnex?" in href:
                    row.exam_annex_url = row.exam_annex_url or href
                elif "/BookAgenda/ViewExamRecord?" in href and href not in seen_exam:
                    seen_exam.add(href)
                    q = parse_qs(urlparse(href).query)
                    row.exam_records.append(ExamRecordLink(
                        exam_id=q.get("examId", [""])[0],
                        exam_name=q.get("examName", [text])[0],
                        url=href))
            rows.append(row)
        return rows

    @staticmethod
    def parse_exam_annex(html_text: str) -> List[AnnexPdfLink]:
        """解析審查會會議紀錄清單頁，取得所有 PDF 標題與網址。"""
        soup = BeautifulSoup(html_text, "html.parser")
        links: List[AnnexPdfLink] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue
            title = "".join(a.get_text().split())
            links.append(AnnexPdfLink(title=title, url=urljoin(BASE_URL, href)))
        return links


class NtpCouncilCrawler:
    """新北市議會議事錄爬蟲（高階介面）。"""

    def __init__(self, fetcher: IFetcher, page_parser: AgendaPageParser = AgendaPageParser()) -> None:
        """建立爬蟲。

        Args:
            fetcher: 下載器實作
            page_parser: 頁面解析器
        """
        self.fetcher = fetcher
        self._parser = page_parser

    def fetch_sessions(self, term_prefix: str = "第4屆") -> List[SessionInfo]:
        """取得指定屆次所有會期。"""
        return self._parser.parse_index(self.fetcher.fetch_text(INDEX_URL), term_prefix)

    def fetch_agenda_rows(self, session: SessionInfo) -> List[AgendaRow]:
        """取得會期日程表每一天的資料。"""
        return self._parser.parse_agenda(self.fetcher.fetch_text(session.url))

    def fetch_exam_annex(self, url: str) -> List[AnnexPdfLink]:
        """取得審查會會議紀錄清單頁中的 PDF。"""
        return self._parser.parse_exam_annex(self.fetcher.fetch_text(url))
