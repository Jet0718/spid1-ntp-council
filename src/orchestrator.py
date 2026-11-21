"""檢索、解析、統計、匯出的整體流程協調器。

高階流程只依賴各元件的抽象行為，元件由建構子注入（依賴反轉原則），
因此可以在單元測試中改用假的下載器，完全離線驗證整條流程。
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar

from .aggregator import RATE_LABELS, StatsAggregator
from .crawler import INDEX_URL, NtpCouncilCrawler
from .exporter import IReportExporter
from .html_parser import HtmlTranscriptParser
from .models import (CATEGORY_COMMITTEE, CATEGORY_PLENARY, AgendaRow, MeetingRecord,
                     MeetingSource, PdfParseResult, SessionInfo)
from .pdf_parser import PdfRecordParser
from .registry import CouncilorRegistry

logger = logging.getLogger(__name__)
T = TypeVar("T")
R = TypeVar("R")


def _to_digit(ch: str) -> str:
    """把全形數字或中文數字轉為半形數字字元。"""
    table = {"０": "0", "１": "1", "２": "2", "３": "3", "４": "4", "５": "5", "６": "6", "７": "7",
             "８": "8", "９": "9", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6",
             "七": "7", "八": "8", "九": "9"}
    return table.get(ch, ch)


def committee_key(text: str, exam_id: str = "") -> str:
    """把審查會 PDF 標題或議事錄代碼統一成委員會名稱，用來配對 PDF 與 HTML。

    例如「1150814第5審查會會議紀錄」、examId=05「第5審查委員會」都會得到「第5審查會」。
    """
    if exam_id.isdigit():
        return f"第{int(exam_id)}審查會"
    if exam_id.upper() == "LR":
        return "法規審查會"
    m = re.search(r"第\s*([0-9０-９一二三四五六七八九])\s*審", text)
    if m:
        return f"第{_to_digit(m.group(1))}審查會"
    for kw, name in (("法規", "法規審查會"), ("紀律", "紀律委員會"), ("程序", "程序委員會")):
        if kw in text:
            return name
    cleaned = re.sub(r"^\d+", "", text)
    return re.sub(r"(會議)?(紀錄|記錄)$", "", cleaned) or text


def short_title(pdf_title: str) -> str:
    """去除標題中的「新北市議會第4屆第N次定期會」前綴，保留場次名稱。"""
    m = re.search(r"(定期會|臨時會|成立大會)", pdf_title)
    rest = pdf_title[m.end():] if m else pdf_title
    return rest or pdf_title


@dataclass
class RunSummary:
    """一次執行的摘要資訊。"""

    sessions: List[str] = field(default_factory=list)  # 處理的會期
    meetings: int = 0  # 有效會議場次
    plenary: int = 0  # 大會場次
    committee: int = 0  # 審查會場次
    skipped: int = 0  # 無可用資料而略過的場次
    scanned_pdfs: int = 0  # 無文字層的 PDF 數
    sign_in_meetings: int = 0  # 出席欄為簽到簿的場次
    discovered: List[str] = field(default_factory=list)  # 自動補入名冊的議員
    councilors: int = 0  # 統計的議員人數
    failed_urls: List[str] = field(default_factory=list)  # 下載失敗網址
    output_path: Optional[Path] = None


class CouncilStatsOrchestrator:
    """議員出席與質詢統計流程協調器。"""

    def __init__(self, crawler: NtpCouncilCrawler, registry: CouncilorRegistry,
                 exporter: IReportExporter, pdf_parser: Optional[PdfRecordParser] = None,
                 html_parser: Optional[HtmlTranscriptParser] = None,
                 aggregator: Optional[StatsAggregator] = None, workers: int = 8) -> None:
        """建立協調器並注入各元件。

        Args:
            crawler: 議事錄爬蟲
            registry: 議員名冊
            exporter: 報表匯出器
            pdf_parser: PDF 解析器
            html_parser: 逐字稿解析器
            aggregator: 統計引擎
            workers: 並行下載執行緒數
        """
        self.crawler = crawler
        self.registry = registry
        self.exporter = exporter
        self.pdf_parser = pdf_parser or PdfRecordParser()
        self.html_parser = html_parser or HtmlTranscriptParser()
        self.aggregator = aggregator or StatsAggregator()
        self.workers = max(1, workers)
        self.summary = RunSummary()

    # ------------------------------------------------------------------ 工具
    def _parallel(self, func: Callable[[T], R], items: Sequence[T], label: str) -> List[Optional[R]]:
        """並行執行，單一項目失敗時記錄並回傳 None，不中斷整體流程。"""

        def safe(item: T) -> Optional[R]:
            try:
                return func(item)
            except Exception as exc:
                logger.warning("%s 失敗：%s（%s）", label, item, exc)
                self.summary.failed_urls.append(str(item))
                return None

        if not items:
            return []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            results = list(pool.map(safe, items))
        logger.info("%s：完成 %d 項", label, len(items))
        return results

    # ------------------------------------------------------------------ 1. 收集來源
    def collect_sources(self, sessions: List[SessionInfo]) -> List[MeetingSource]:
        """從各會期日程表收集所有大會與審查會場次的原始來源。"""
        rows_list = self._parallel(self.crawler.fetch_agenda_rows, sessions, "下載會期日程表")
        annex_urls = sorted({r.exam_annex_url for rows in rows_list if rows for r in rows if r.exam_annex_url})
        annex_results = self._parallel(self.crawler.fetch_exam_annex, annex_urls, "下載審查會紀錄清單")
        annex_map = dict(zip(annex_urls, annex_results))

        sources: List[MeetingSource] = []
        for session, rows in zip(sessions, rows_list):
            for row in rows or []:
                sources.extend(self._sources_from_row(session, row, annex_map))
        return sources

    @staticmethod
    def _agenda_text(row: AgendaRow) -> str:
        """組合上午／下午議程文字。"""
        parts = []
        if row.am_agenda:
            parts.append(f"上午：{row.am_agenda}")
        if row.pm_agenda:
            parts.append(f"下午：{row.pm_agenda}")
        return "；".join(parts)

    def _sources_from_row(self, session: SessionInfo, row: AgendaRow,
                          annex_map: Dict[str, Optional[list]]) -> List[MeetingSource]:
        """把日程表的一列拆成大會場次與各審查會場次。"""
        result: List[MeetingSource] = []
        agenda = self._agenda_text(row)
        base_id = f"{session.session_id}|{row.date_str}"
        if row.summary_pdf_url or row.record_url:
            result.append(MeetingSource(
                meeting_id=f"{base_id}|大會", session_name=session.session_name, date_str=row.date_str,
                category=CATEGORY_PLENARY, title=f"第{row.order}次會議" if row.order else "",
                agenda=agenda, pdf_urls=[row.summary_pdf_url] if row.summary_pdf_url else [],
                html_url=row.record_url))

        committees: Dict[str, MeetingSource] = {}

        def get(key: str) -> MeetingSource:
            """取得或建立某審查會的來源物件。"""
            if key not in committees:
                committees[key] = MeetingSource(
                    meeting_id=f"{base_id}|{key}", session_name=session.session_name,
                    date_str=row.date_str, category=CATEGORY_COMMITTEE, title=key, agenda=agenda)
            return committees[key]

        for link in (annex_map.get(row.exam_annex_url) or []) if row.exam_annex_url else []:
            if "附件" in link.title or not ("紀錄" in link.title or "記錄" in link.title):
                continue
            get(committee_key(link.title)).pdf_urls.append(link.url)
        for rec in row.exam_records:
            get(committee_key(rec.exam_name, rec.exam_id)).html_url = rec.url
        result.extend(committees[k] for k in sorted(committees))
        return result

    # ------------------------------------------------------------------ 2. 下載並解析
    def fetch_and_parse(self, sources: List[MeetingSource]) -> Tuple[Dict[str, PdfParseResult], Dict[str, Counter]]:
        """下載並解析所有 PDF 與 HTML。"""
        pdf_urls = sorted({u for s in sources for u in s.pdf_urls})
        html_urls = sorted({s.html_url for s in sources if s.html_url})
        pdfs = self._parallel(lambda u: self.pdf_parser.parse_bytes(self.crawler.fetcher.fetch_bytes(u)),
                              pdf_urls, "下載解析 PDF")
        htmls = self._parallel(lambda u: self.html_parser.parse_speakers(self.crawler.fetcher.fetch_text(u)),
                               html_urls, "下載解析逐字稿")
        pdf_map = {u: r for u, r in zip(pdf_urls, pdfs) if r is not None}
        html_map = {u: r for u, r in zip(html_urls, htmls) if r is not None}
        self.summary.scanned_pdfs = sum(1 for r in pdf_map.values() if not r.has_text)
        return pdf_map, html_map

    # ------------------------------------------------------------------ 3. 名冊補入
    def discover_councilors(self, pdf_map: Dict[str, PdfParseResult], html_map: Dict[str, Counter]) -> List[str]:
        """從出席／請假欄與逐字稿中自動補入不在種子名冊的議員（離職、補選等）。"""
        candidates: List[str] = []
        for r in pdf_map.values():
            for raw in (None if r.sign_in_book else r.attend_raw, r.leave_raw):
                candidates.extend(self.registry.extract_from_block(raw)[1])
        for speakers in html_map.values():
            for label, cnt in speakers.items():
                if self.registry.extract_councilor_from_speaker(label) is None:
                    cand = self.registry.speaker_candidate(label)
                    if cand:
                        candidates.extend([cand] * min(cnt, 1))
        return self.registry.discover(candidates, min_count=2)

    # ------------------------------------------------------------------ 4. 組成會議紀錄
    def build_record(self, src: MeetingSource, pdf_map: Dict[str, PdfParseResult],
                     html_map: Dict[str, Counter]) -> Optional[MeetingRecord]:
        """把一個場次的原始來源轉成 MeetingRecord；完全沒有可用資料時回傳 None。"""
        rec = MeetingRecord(meeting_id=src.meeting_id, session_name=src.session_name, date_str=src.date_str,
                            category=src.category, title=src.title, agenda=src.agenda,
                            pdf_urls=list(src.pdf_urls), html_url=src.html_url)
        for url in src.pdf_urls:
            r = pdf_map.get(url)
            if r is None:
                rec.notes.append("PDF 下載失敗")
                continue
            if not r.has_text:
                rec.pdf_has_text = False
                rec.notes.append("PDF 為掃描影像，無法擷取文字")
                continue
            if src.category == CATEGORY_PLENARY and r.title:
                rec.title = short_title(r.title)
            if r.sign_in_book:
                rec.sign_in_book = True
            else:
                rec.attendees |= self.registry.extract_from_block(r.attend_raw)[0]
            rec.leaves |= self.registry.extract_from_block(r.leave_raw)[0]
            rec.questioners |= self.registry.find_mentions(r.full_text)
        if src.html_url:
            speakers = html_map.get(src.html_url)
            if speakers is None:
                rec.notes.append("逐字稿下載失敗")
            else:
                for label, cnt in speakers.items():
                    name = self.registry.extract_councilor_from_speaker(label)
                    if name:
                        rec.questioners.add(name)
                        rec.speech_counts[name] += cnt
        rec.attendees -= rec.leaves  # 同時列於出席與請假者以請假為準
        rec.has_attendance_list = bool(rec.attendees) and not rec.sign_in_book
        if rec.sign_in_book:
            rec.notes.append("出席欄為「詳如簽到簿」，不計入出席率分母")
        if not (rec.attendees or rec.leaves or rec.questioners or rec.sign_in_book):
            return None
        if not rec.title:
            rec.title = src.agenda[:30]
        return rec

    # ------------------------------------------------------------------ 主流程
    def run(self, output_path: Path, session_filters: Iterable[str] = (),
            term_prefix: str = "第4屆") -> RunSummary:
        """執行完整流程：檢索 → 解析 → 名冊補入 → 統計 → 匯出。

        Args:
            output_path: Excel 輸出路徑
            session_filters: 會期名稱關鍵字（任一符合即納入）；空值表示全部
            term_prefix: 屆次前綴
        Returns:
            RunSummary 執行摘要
        """
        self.summary = RunSummary()
        sessions = self.crawler.fetch_sessions(term_prefix)
        filters = [f for f in session_filters if f]
        if filters:
            sessions = [s for s in sessions if any(f in s.session_name for f in filters)]
        if not sessions:
            raise ValueError("找不到符合條件的會期")
        self.summary.sessions = [s.session_name for s in sessions]
        logger.info("共 %d 個會期：%s", len(sessions), "、".join(self.summary.sessions))

        sources = self.collect_sources(sessions)
        logger.info("共 %d 個候選場次", len(sources))
        pdf_map, html_map = self.fetch_and_parse(sources)
        self.summary.discovered = self.discover_councilors(pdf_map, html_map)
        if self.summary.discovered:
            logger.info("自動補入名冊：%s", "、".join(self.summary.discovered))

        meetings: List[MeetingRecord] = []
        for src in sources:
            rec = self.build_record(src, pdf_map, html_map)
            if rec is None:
                self.summary.skipped += 1
            else:
                meetings.append(rec)
        meetings.sort(key=lambda m: (m.date_str, m.category != CATEGORY_PLENARY, m.title))

        stats = self.aggregator.aggregate(meetings, self.registry.names)
        self.summary.meetings = len(meetings)
        self.summary.plenary = sum(1 for m in meetings if m.category == CATEGORY_PLENARY)
        self.summary.committee = self.summary.meetings - self.summary.plenary
        self.summary.sign_in_meetings = sum(1 for m in meetings if m.sign_in_book)
        self.summary.councilors = len(stats)
        self.summary.output_path = self.exporter.export(stats, meetings, output_path, self._notes(term_prefix))
        return self.summary

    def _notes(self, term_prefix: str) -> List[Tuple[str, str]]:
        """產生「統計說明」工作表內容。"""
        s = self.summary
        return [
            ("資料來源", f"新北市議會議事錄系統 {INDEX_URL}"),
            ("檢索時間", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("檢索範圍", f"{term_prefix}，共 {len(s.sessions)} 個會期：{'、'.join(s.sessions)}"),
            ("有效會議場次", f"共 {s.meetings} 場（大會 {s.plenary} 場、審查會 {s.committee} 場）；"
                             f"無任何可用資料而略過 {s.skipped} 場"),
            ("出席欄為「詳如簽到簿」場次", f"{s.sign_in_meetings} 場：不計入出席率分母，請假與質詢照常計入"),
            ("掃描影像 PDF", f"{s.scanned_pdfs} 份無法擷取文字；若該場次有逐字稿仍以逐字稿取得質詢名單"),
            ("下載失敗", f"{len(s.failed_urls)} 項" + (f"：{'、'.join(s.failed_urls[:20])}" if s.failed_urls else "")),
            ("自動補入名冊之議員", "、".join(s.discovered) or "無"),
            ("僅記錄市議員", "出席／請假名單取自 PDF「出席」「請假」欄（排除「列席」官員與行政人員）；"
                           "逐字稿只計入標示為「○議員○○」「○委員○○」「○召集人○○」且在名冊中的發言者，"
                           "「主席」主持議事與官員發言不計入"),
            ("質詢判定", "逐字稿中有發言，或摘要/會議紀錄 PDF 內以「○議員○○」形式被列為提問、要求者，"
                       "即計為該場次有質詢（同場多次發言只計 1 場）"),
            (RATE_LABELS["attendance_all"], "實際出席總場次 ÷ 總會議場次數（大會+審查會）"),
            (RATE_LABELS["attendance_list"], "實際出席總場次 ÷ 有出席名單之會議場次"),
            (RATE_LABELS["attendance_expected"], "實際出席總場次 ÷ (實際出席 + 請假)；審查會只有所屬委員須出席，此指標較能反映應到出席情形"),
            (RATE_LABELS["question_all"], "總質詢場次數 ÷ 總會議場次數"),
            (RATE_LABELS["question_attended"], "出席且有質詢的場次 ÷ 實際出席總場次"),
            (RATE_LABELS["plenary_attendance"], "大會出席場次 ÷ 大會有出席名單場次"),
            (RATE_LABELS["plenary_question"], "大會質詢場次 ÷ 大會總場次"),
            ("任期內指標", "以議員在紀錄中首次與最後出現的日期推定在任期間（反映任期中離職或補選）"),
            ("限制", "資料完全依網站公開文件自動解析；PDF 排版異常、掃描檔或網站缺漏的紀錄可能造成少計，"
                   "建議對重要數字以「各場次會議明細表」中的原始連結抽查"),
        ]
