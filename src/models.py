"""資料模型定義模組。

集中定義系統各層之間傳遞的資料結構（DTO），
各模組只依賴這些純資料類別，降低彼此耦合（S.O.L.I.D 之 S 與 D）。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

# 會議類別常數
CATEGORY_PLENARY = "大會"  # 大會（含預備會議、施政報告、業務質詢、總質詢、讀會等）
CATEGORY_COMMITTEE = "審查會"  # 審查委員會


@dataclass(frozen=True)
class SessionInfo:
    """會期資訊。

    Attributes:
        session_id: 會期 GUID（網址參數 cBookMdslID）
        session_name: 會期名稱，例如「第4屆第8次定期會」
        url: 會期日程表完整網址
    """

    session_id: str
    session_name: str
    url: str


@dataclass(frozen=True)
class ExamRecordLink:
    """審查會議事錄（HTML 逐字稿）連結。

    Attributes:
        exam_id: 審查會代碼（01~06、LR 等）
        exam_name: 審查會名稱，例如「第5審查委員會」
        url: 議事錄完整網址
    """

    exam_id: str
    exam_name: str
    url: str


@dataclass
class AgendaRow:
    """日程表中的一列（一天）。

    Attributes:
        date_str: 民國日期字串，例如「115-08-05」
        order: 議次欄位內容（可能為空）
        am_agenda: 上午議程文字
        pm_agenda: 下午議程文字
        summary_pdf_url: 大會摘要紀錄 PDF 網址
        record_url: 大會會議紀錄（HTML 逐字稿）網址
        exam_annex_url: 審查會會議紀錄清單頁（ViewExamAnnex）網址
        exam_records: 各審查會議事錄連結
    """

    date_str: str
    order: str = ""
    am_agenda: str = ""
    pm_agenda: str = ""
    summary_pdf_url: Optional[str] = None
    record_url: Optional[str] = None
    exam_annex_url: Optional[str] = None
    exam_records: List[ExamRecordLink] = field(default_factory=list)


@dataclass(frozen=True)
class AnnexPdfLink:
    """審查會會議紀錄清單頁中的單一 PDF 連結。"""

    title: str  # PDF 標題，例如「1150814第5審查會會議紀錄」
    url: str  # PDF 完整網址


@dataclass
class MeetingSource:
    """單一會議場次的原始來源（尚未解析）。"""

    meeting_id: str  # 場次唯一識別碼
    session_name: str  # 會期名稱
    date_str: str  # 會議日期
    category: str  # 會議類別（大會 / 審查會）
    title: str  # 議次或委員會名稱
    agenda: str  # 議程摘要
    pdf_urls: List[str] = field(default_factory=list)  # 摘要紀錄或審查會紀錄 PDF
    html_url: Optional[str] = None  # 會議紀錄或議事錄 HTML


@dataclass
class PdfParseResult:
    """PDF 文字解析的原始結果（姓名尚未對應名冊）。"""

    has_text: bool = False  # PDF 是否有可擷取文字（掃描檔為 False）
    title: str = ""  # 文件標題列
    attend_raw: Optional[str] = None  # 出席欄位原始文字（None 表示沒有出席欄）
    leave_raw: Optional[str] = None  # 請假欄位原始文字
    sign_in_book: bool = False  # 出席欄為「詳如簽到簿」
    full_text: str = ""  # 全文（供質詢名單比對）


@dataclass
class MeetingRecord:
    """解析完成的單一會議場次紀錄。"""

    meeting_id: str
    session_name: str
    date_str: str
    category: str
    title: str
    agenda: str
    attendees: Set[str] = field(default_factory=set)  # 出席議員
    leaves: Set[str] = field(default_factory=set)  # 請假議員
    questioners: Set[str] = field(default_factory=set)  # 質詢／發言議員
    speech_counts: Counter = field(default_factory=Counter)  # 議員發言段落數
    has_attendance_list: bool = False  # 是否有可用的出席名單
    sign_in_book: bool = False  # 出席欄為「詳如簽到簿」
    pdf_urls: List[str] = field(default_factory=list)
    html_url: Optional[str] = None
    pdf_has_text: bool = True  # PDF 是否有文字層
    notes: List[str] = field(default_factory=list)  # 解析備註


@dataclass
class CouncilorStats:
    """單一議員的統計結果。"""

    name: str
    total_meetings: int = 0  # 全部有效會議場次
    meetings_with_list: int = 0  # 有出席名單之場次（出席率分母）
    attended: int = 0  # 實際出席總場次
    leave: int = 0  # 請假總場次
    questioned: int = 0  # 質詢總場次
    speech_paragraphs: int = 0  # 逐字稿發言段落數
    plenary_total: int = 0  # 大會總場次
    plenary_with_list: int = 0  # 大會有出席名單場次
    plenary_attended: int = 0
    plenary_leave: int = 0
    plenary_questioned: int = 0
    committee_attended: int = 0
    committee_leave: int = 0
    committee_questioned: int = 0
    first_date: Optional[str] = None  # 首次出現日期
    last_date: Optional[str] = None  # 最後出現日期
    tenure_meetings: int = 0  # 任期內會議場次
    tenure_with_list: int = 0  # 任期內有出席名單場次
    rates: Dict[str, Optional[float]] = field(default_factory=dict)  # 各項比率
