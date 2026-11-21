"""出席率與質詢率統計計算引擎。

職責：把多場 MeetingRecord 彙總成每位議員的 CouncilorStats。
計算公式詳見 spec.md 第 4.4、4.5 節。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .models import CATEGORY_PLENARY, CouncilorStats, MeetingRecord

# 比率欄位代碼與中文說明（供匯出器與文件共用）
RATE_LABELS: Dict[str, str] = {
    "attendance_all": "總出席率(占全體會議場次)",
    "attendance_list": "出席率(占有出席名單場次)",
    "attendance_expected": "應到場次出席率(出席/(出席+請假))",
    "question_all": "總質詢率(占全體會議場次)",
    "question_attended": "出席場次質詢率(出席且質詢/出席)",
    "plenary_attendance": "大會出席率",
    "plenary_question": "大會質詢率",
    "tenure_attendance": "任期內出席率",
    "tenure_question": "任期內質詢率",
}


def safe_ratio(numerator: int, denominator: int) -> Optional[float]:
    """安全除法：分母為 0 時回傳 None。"""
    return numerator / denominator if denominator else None


class StatsAggregator:
    """議員出席與質詢統計引擎。"""

    def aggregate(self, meetings: List[MeetingRecord],
                  councilors: Optional[Iterable[str]] = None) -> List[CouncilorStats]:
        """計算每位議員的統計結果。

        Args:
            meetings: 所有有效會議場次
            councilors: 要統計的議員清單；None 表示統計所有在紀錄中出現過的議員
        Returns:
            依姓名排序的 CouncilorStats 清單（從未出現在任何紀錄者不列入）
        """
        appeared = set()
        for m in meetings:
            appeared |= m.attendees | m.leaves | m.questioners
        names = sorted(appeared if councilors is None else set(councilors) & appeared)

        total = len(meetings)
        with_list = sum(1 for m in meetings if m.has_attendance_list)
        plenary = [m for m in meetings if m.category == CATEGORY_PLENARY]
        plenary_total = len(plenary)
        plenary_with_list = sum(1 for m in plenary if m.has_attendance_list)

        return [self._build(name, meetings, total, with_list, plenary_total, plenary_with_list)
                for name in names]

    @staticmethod
    def _build(name: str, meetings: List[MeetingRecord], total: int, with_list: int,
               plenary_total: int, plenary_with_list: int) -> CouncilorStats:
        """計算單一議員的統計。"""
        s = CouncilorStats(name=name, total_meetings=total, meetings_with_list=with_list,
                           plenary_total=plenary_total, plenary_with_list=plenary_with_list)
        q_when_attended = 0  # 出席且有質詢的場次
        dates: List[str] = []
        for m in meetings:
            is_plenary = m.category == CATEGORY_PLENARY
            att, lv, qs = name in m.attendees, name in m.leaves, name in m.questioners
            if att or lv or qs:
                dates.append(m.date_str)
            if att:
                s.attended += 1
                if is_plenary:
                    s.plenary_attended += 1
                else:
                    s.committee_attended += 1
                if qs:
                    q_when_attended += 1
            if lv:
                s.leave += 1
                if is_plenary:
                    s.plenary_leave += 1
                else:
                    s.committee_leave += 1
            if qs:
                s.questioned += 1
                if is_plenary:
                    s.plenary_questioned += 1
                else:
                    s.committee_questioned += 1
            s.speech_paragraphs += m.speech_counts.get(name, 0)

        # 民國日期字串（如 112-04-25、115-08-05）位數一致，可直接以字串比較
        if dates:
            s.first_date, s.last_date = min(dates), max(dates)
            tenure = [m for m in meetings if s.first_date <= m.date_str <= s.last_date]
            s.tenure_meetings = len(tenure)
            s.tenure_with_list = sum(1 for m in tenure if m.has_attendance_list)

        s.rates = {
            "attendance_all": safe_ratio(s.attended, total),
            "attendance_list": safe_ratio(s.attended, with_list),
            "attendance_expected": safe_ratio(s.attended, s.attended + s.leave),
            "question_all": safe_ratio(s.questioned, total),
            "question_attended": safe_ratio(q_when_attended, s.attended),
            "plenary_attendance": safe_ratio(s.plenary_attended, plenary_with_list),
            "plenary_question": safe_ratio(s.plenary_questioned, plenary_total),
            "tenure_attendance": safe_ratio(s.attended, s.tenure_with_list),
            "tenure_question": safe_ratio(s.questioned, s.tenure_meetings),
        }
        return s
