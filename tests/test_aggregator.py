"""StatsAggregator 統計計算與 ExcelReportExporter 匯出單元測試。"""
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from src.aggregator import RATE_LABELS, StatsAggregator, safe_ratio
from src.exporter import SHEET_DETAIL, SHEET_NOTES, SHEET_SUMMARY, ExcelReportExporter
from src.models import CATEGORY_COMMITTEE, CATEGORY_PLENARY, MeetingRecord


def make_meeting(mid, date, cat, att=(), lv=(), qs=(), has_list=True, sign_in=False):
    """建立測試用會議紀錄。"""
    return MeetingRecord(meeting_id=mid, session_name="第4屆第1次定期會", date_str=date, category=cat,
                         title=mid, agenda="", attendees=set(att), leaves=set(lv), questioners=set(qs),
                         speech_counts=Counter({q: 2 for q in qs}), has_attendance_list=has_list,
                         sign_in_book=sign_in)


class TestAggregator(unittest.TestCase):
    """統計計算測試。"""

    def setUp(self):
        """建立 4 場會議：3 場大會（其中 1 場為簽到簿）、1 場審查會。"""
        self.meetings = [
            make_meeting("M1", "112-04-25", CATEGORY_PLENARY, att=["甲", "乙"], lv=["丙"], qs=["甲"]),
            make_meeting("M2", "112-04-26", CATEGORY_PLENARY, att=["甲"], lv=["乙"], qs=["甲", "乙"]),
            make_meeting("M3", "112-04-27", CATEGORY_PLENARY, lv=["丙"], qs=["乙"], has_list=False, sign_in=True),
            make_meeting("M4", "112-05-01", CATEGORY_COMMITTEE, att=["甲"], qs=["甲"]),
        ]
        self.stats = {s.name: s for s in StatsAggregator().aggregate(self.meetings)}

    def test_safe_ratio(self):
        """分母為 0 回傳 None。"""
        self.assertIsNone(safe_ratio(1, 0))
        self.assertEqual(safe_ratio(1, 4), 0.25)

    def test_counts_and_rates_for_jia(self):
        """甲：出席 3 場（大會 2、審查會 1）、質詢 3 場。"""
        s = self.stats["甲"]
        self.assertEqual((s.total_meetings, s.meetings_with_list), (4, 3))
        self.assertEqual((s.attended, s.plenary_attended, s.committee_attended), (3, 2, 1))
        self.assertEqual((s.questioned, s.plenary_questioned, s.committee_questioned), (3, 2, 1))
        self.assertAlmostEqual(s.rates["attendance_all"], 3 / 4)
        self.assertAlmostEqual(s.rates["attendance_list"], 3 / 3)
        self.assertAlmostEqual(s.rates["attendance_expected"], 1.0)
        self.assertAlmostEqual(s.rates["question_all"], 3 / 4)
        self.assertAlmostEqual(s.rates["question_attended"], 1.0)
        self.assertAlmostEqual(s.rates["plenary_attendance"], 2 / 2)  # 大會有名單場次=2
        self.assertAlmostEqual(s.rates["plenary_question"], 2 / 3)
        self.assertEqual(s.speech_paragraphs, 6)

    def test_sign_in_meeting_excluded_from_attendance(self):
        """乙：簽到簿場次有質詢但不算出席；出席場次質詢率只看出席場次。"""
        s = self.stats["乙"]
        self.assertEqual((s.attended, s.leave, s.questioned), (1, 1, 2))
        self.assertAlmostEqual(s.rates["attendance_expected"], 0.5)
        self.assertAlmostEqual(s.rates["question_attended"], 0.0)  # 唯一出席的 M1 沒有質詢
        self.assertAlmostEqual(s.rates["question_all"], 2 / 4)

    def test_tenure(self):
        """丙：首末出現日期 M1~M3，任期內 3 場、其中 2 場有名單。"""
        s = self.stats["丙"]
        self.assertEqual((s.first_date, s.last_date), ("112-04-25", "112-04-27"))
        self.assertEqual((s.tenure_meetings, s.tenure_with_list), (3, 2))
        self.assertAlmostEqual(s.rates["tenure_attendance"], 0.0)
        self.assertIsNone(s.rates["question_attended"])  # 從未出席

    def test_councilor_filter(self):
        """指定議員清單時只統計交集，未出現者不列入。"""
        result = StatsAggregator().aggregate(self.meetings, councilors=["甲", "丁"])
        self.assertEqual([s.name for s in result], ["甲"])


class TestExporter(unittest.TestCase):
    """Excel 匯出測試。"""

    def test_export_workbook(self):
        """匯出後應有三個工作表，數值與百分比格式正確。"""
        meetings = [
            make_meeting("M1", "112-04-25", CATEGORY_PLENARY, att=["甲", "乙"], lv=["丙"], qs=["甲"]),
            make_meeting("M2", "112-04-27", CATEGORY_PLENARY, lv=["丙"], qs=["乙"], has_list=False, sign_in=True),
        ]
        stats = StatsAggregator().aggregate(meetings)
        with tempfile.TemporaryDirectory() as tmp:
            path = ExcelReportExporter().export(stats, meetings, Path(tmp) / "out.xlsx",
                                                notes=[("資料來源", "測試")])
            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, [SHEET_SUMMARY, SHEET_DETAIL, SHEET_NOTES])
            ws = wb[SHEET_SUMMARY]
            headers = [c.value for c in ws[1]]
            names = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
            self.assertEqual(sorted(names), sorted(["甲", "乙", "丙"]))
            row = names.index("甲") + 2
            col = headers.index(RATE_LABELS["question_all"]) + 1
            self.assertAlmostEqual(ws.cell(row, col).value, 0.5)
            self.assertEqual(ws.cell(row, col).number_format, "0.00%")
            detail = wb[SHEET_DETAIL]
            dh = [c.value for c in detail[1]]
            self.assertEqual(detail.cell(2, dh.index("出席議員名單") + 1).value, "乙、甲")
            self.assertEqual(detail.cell(3, dh.index("出席議員名單") + 1).value, "詳如簽到簿")
            wb.close()


if __name__ == "__main__":
    unittest.main()
