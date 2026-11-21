"""Excel 報表匯出器。

職責：把統計結果與各場次明細寫成格式化的 Excel 檔（單一職責原則）。
透過 IReportExporter 介面，未來可擴充 CSV、Google Sheets 等輸出（開放封閉原則）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Sequence, Tuple

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .aggregator import RATE_LABELS
from .models import CouncilorStats, MeetingRecord

SHEET_SUMMARY = "議員出席與質詢總統計表"  # 工作表 1
SHEET_DETAIL = "各場次會議明細表"  # 工作表 2
SHEET_NOTES = "統計說明"  # 工作表 3
_HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")  # 表頭底色


class IReportExporter(ABC):
    """報表匯出介面。"""

    @abstractmethod
    def export(self, stats: List[CouncilorStats], meetings: List[MeetingRecord],
               output_path: Path, notes: Sequence[Tuple[str, str]] = ()) -> Path:
        """匯出報表並回傳檔案路徑。"""


def _join(names) -> str:
    """把姓名集合排序後以頓號串接。"""
    return "、".join(sorted(names))


class ExcelReportExporter(IReportExporter):
    """Excel（.xlsx）報表匯出器。"""

    @staticmethod
    def build_summary_frame(stats: List[CouncilorStats]) -> pd.DataFrame:
        """建立「議員出席與質詢總統計表」資料表。"""
        rows = []
        for s in stats:
            r = s.rates
            rows.append({
                "議員姓名": s.name,
                "總會議場次數(大會+審查會)": s.total_meetings,
                "有出席名單之會議場次": s.meetings_with_list,
                "實際出席總場次": s.attended,
                "請假總場次": s.leave,
                RATE_LABELS["attendance_all"]: r["attendance_all"],
                RATE_LABELS["attendance_list"]: r["attendance_list"],
                RATE_LABELS["attendance_expected"]: r["attendance_expected"],
                "總質詢場次數": s.questioned,
                RATE_LABELS["question_all"]: r["question_all"],
                RATE_LABELS["question_attended"]: r["question_attended"],
                "大會總場次": s.plenary_total,
                "大會有出席名單場次": s.plenary_with_list,
                "大會出席場次": s.plenary_attended,
                "大會請假場次": s.plenary_leave,
                RATE_LABELS["plenary_attendance"]: r["plenary_attendance"],
                "大會質詢場次": s.plenary_questioned,
                RATE_LABELS["plenary_question"]: r["plenary_question"],
                "審查會出席場次": s.committee_attended,
                "審查會請假場次": s.committee_leave,
                "審查會質詢場次": s.committee_questioned,
                "首次出現日期": s.first_date,
                "最後出現日期": s.last_date,
                "任期內會議場次": s.tenure_meetings,
                "任期內有出席名單場次": s.tenure_with_list,
                RATE_LABELS["tenure_attendance"]: r["tenure_attendance"],
                RATE_LABELS["tenure_question"]: r["tenure_question"],
                "總發言段落數": s.speech_paragraphs,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def build_detail_frame(meetings: List[MeetingRecord]) -> pd.DataFrame:
        """建立「各場次會議明細表」資料表。"""
        rows = []
        for i, m in enumerate(meetings, 1):
            if m.sign_in_book:
                attend_text = "詳如簽到簿"
            elif not m.has_attendance_list:
                attend_text = "（無出席名單）"
            else:
                attend_text = _join(m.attendees)
            rows.append({
                "場次編號": i,
                "會期名稱": m.session_name,
                "會議日期": m.date_str,
                "會議類別": m.category,
                "議次/委員會名稱": m.title,
                "議程摘要": m.agenda,
                "出席議員人數": len(m.attendees) if m.has_attendance_list else None,
                "出席議員名單": attend_text,
                "請假議員人數": len(m.leaves),
                "請假議員名單": _join(m.leaves),
                "質詢議員人數": len(m.questioners),
                "質詢議員名單": _join(m.questioners),
                "摘要/紀錄PDF連結": "\n".join(m.pdf_urls),
                "會議紀錄/議事錄連結": m.html_url or "",
                "備註": "；".join(m.notes),
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _format_sheet(ws, percent_cols: Sequence[str] = (), wrap_cols: Sequence[str] = (),
                      max_width: int = 60) -> None:
        """設定表頭樣式、凍結窗格、篩選、欄寬與百分比格式。"""
        headers = [c.value for c in ws[1]]
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = _HEADER_FILL
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 45
        for idx, header in enumerate(headers, 1):
            letter = get_column_letter(idx)
            values = [str(c.value) for c in ws[letter][1:200] if c.value is not None]
            longest = max([len(v) for v in values] + [6])
            width = min(max(longest * 1.8, 8), max_width)
            if header in wrap_cols:
                width = max_width
            ws.column_dimensions[letter].width = min(width, max(len(str(header)) * 1.2, width))
            for cell in ws[letter][1:]:
                if header in percent_cols:
                    cell.number_format = "0.00%"
                if header in wrap_cols:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")

    def export(self, stats: List[CouncilorStats], meetings: List[MeetingRecord],
               output_path: Path, notes: Sequence[Tuple[str, str]] = ()) -> Path:
        """匯出三個工作表的 Excel 檔。

        Args:
            stats: 議員統計
            meetings: 會議場次明細
            output_path: 輸出檔案路徑
            notes: 統計說明（項目, 內容）
        Returns:
            輸出檔案路徑
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        summary = self.build_summary_frame(stats)
        detail = self.build_detail_frame(meetings)
        notes_df = pd.DataFrame(list(notes), columns=["項目", "內容"])
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            summary.to_excel(writer, sheet_name=SHEET_SUMMARY, index=False)
            detail.to_excel(writer, sheet_name=SHEET_DETAIL, index=False)
            notes_df.to_excel(writer, sheet_name=SHEET_NOTES, index=False)
            self._format_sheet(writer.sheets[SHEET_SUMMARY], percent_cols=list(RATE_LABELS.values()))
            self._format_sheet(writer.sheets[SHEET_DETAIL],
                               wrap_cols=["出席議員名單", "請假議員名單", "質詢議員名單", "議程摘要"])
            self._format_sheet(writer.sheets[SHEET_NOTES], wrap_cols=["內容"], max_width=100)
        return output_path
