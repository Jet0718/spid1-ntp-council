"""PDF 解析器、HTML 逐字稿解析器與日程表頁面解析器單元測試。"""
import unittest

from src.crawler import AgendaPageParser, build_ssl_context
from src.html_parser import HtmlTranscriptParser
from src.pdf_parser import IPdfTextExtractor, PdfRecordParser

# 實際摘要紀錄 PDF 擷取文字（節錄自第4屆第8次定期會）
PLENARY_TEXT = """第1/6頁
   新北市議會第 4 屆第8 次定期會第 4 次審查委員會
業務質詢會議摘要紀錄
時  間：中華民國 115 年8 月 5 日 14 時
地  點：本會議事廳
出  席：陳家琪  曾煥嘉  蘇錦雄 Paylang．Caya
石一佑  陳錦錠  宋雨蓁 Nikar．Falong
請  假：宋明宗  白珮茹  馬見 Lahuy．Ipin
列  席：專門委員林順全   副市長劉和然
主  席：鍾召集人宏仁    記錄：蔡雅芳
乙、一至六審各機關聯合業務報告及質詢
有陳議員偉杰、呂議員家愷等提出多項問題
"""

# 實際審查會會議紀錄 PDF 擷取文字
COMMITTEE_TEXT = """新北市議會第4屆第8次定期會第2審查會審查議案會議紀錄
時間：中華民國115年8月14日14時20分
地點：第2審查會會議室
出席：張維倩 山田摩衣 陳明義 許昭興 陳家琪
林秉宥 鍾宏仁  王威元
列席：汪禮國 林順全
請假：江怡臻
主席：林秉宥召集人    記錄：蔡雅芳
"""

SIGN_IN_TEXT = """新北市議會第 4 屆第 1 次定期會
第 1 次市政總質詢會議摘要紀錄
時  間：中華民國 112 年4 月 27 日 10 時
出  席：詳如簽到簿
請  假：黃俊哲  宋雨蓁 Nikar．Falong
列  席：秘書長陳王正源
"""


class FakeExtractor(IPdfTextExtractor):
    """測試用假擷取器：直接回傳預設文字。"""

    def __init__(self, text):
        """保存要回傳的文字。"""
        self.text = text

    def extract(self, pdf_bytes):
        """忽略輸入，回傳預設文字。"""
        return self.text


class TestPdfParser(unittest.TestCase):
    """PdfRecordParser 測試。"""

    def test_plenary_fields(self):
        """大會摘要：標題、出席、請假欄位切分正確，列席不混入。"""
        r = PdfRecordParser().parse_text(PLENARY_TEXT)
        self.assertTrue(r.has_text)
        self.assertEqual(r.title, "新北市議會第4屆第8次定期會第4次審查委員會業務質詢會議摘要紀錄")
        self.assertIn("陳家琪", r.attend_raw)
        self.assertIn("Nikar．Falong", r.attend_raw)
        self.assertNotIn("宋明宗", r.attend_raw)
        self.assertIn("馬見", r.leave_raw)
        self.assertNotIn("林順全", r.leave_raw)
        self.assertFalse(r.sign_in_book)

    def test_committee_fields(self):
        """審查會紀錄：列席在請假之前時，出席欄不可包含列席人員。"""
        r = PdfRecordParser().parse_text(COMMITTEE_TEXT)
        self.assertIn("王威元", r.attend_raw)
        self.assertNotIn("汪禮國", r.attend_raw)
        self.assertEqual(r.leave_raw, "江怡臻")

    def test_sign_in_book(self):
        """出席欄為「詳如簽到簿」時應標記。"""
        r = PdfRecordParser().parse_text(SIGN_IN_TEXT)
        self.assertTrue(r.sign_in_book)
        self.assertIn("黃俊哲", r.leave_raw)

    def test_scanned_pdf(self):
        """掃描檔（無文字）應標記為無文字層。"""
        r = PdfRecordParser(FakeExtractor("  \n ")).parse_bytes(b"%PDF")
        self.assertFalse(r.has_text)
        self.assertIsNone(r.attend_raw)


class TestHtmlParser(unittest.TestCase):
    """HtmlTranscriptParser 測試。"""

    def test_speakers(self):
        """取出發言者標籤並計算段落數。"""
        html = """<table>
        <tr><td style="white-space: nowrap;" valign="top">主　　　席：</td><td>開會</td></tr>
        <tr><td valign="top">陳議員偉杰：</td><td>請問局長</td></tr>
        <tr><td valign="top">宋局長德仁：</td><td>報告議員</td></tr>
        <tr><td valign="top">陳議員偉杰：</td><td>謝謝</td></tr>
        <tr><td valign="top">　　　　　　</td><td>主席 蔣根煌</td></tr>
        </table>"""
        sp = HtmlTranscriptParser().parse_speakers(html)
        self.assertEqual(sp["陳議員偉杰："], 2)
        self.assertEqual(sp["主席："], 1)
        self.assertEqual(sp["宋局長德仁："], 1)
        self.assertEqual(len(sp), 3)


class TestAgendaPageParser(unittest.TestCase):
    """AgendaPageParser 測試。"""

    def test_parse_index(self):
        """只取第4屆會期並去除重複。"""
        html = """<a href="/Home/BookAgenda?cBookMdslID=aaa" class="list-group-item">
            <p class="list-group-item-text">第4屆第8次定期會</p></a>
            <a href="/Home/BookAgenda?cBookMdslID=aaa"><p>第4屆第8次定期會</p></a>
            <a href="/Home/BookAgenda?cBookMdslID=bbb"><p>第3屆第8次定期會</p></a>"""
        s = AgendaPageParser.parse_index(html)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0].session_name, "第4屆第8次定期會")
        self.assertEqual(s[0].url, "https://ntpbook.ntp.gov.tw/Home/BookAgenda?cBookMdslID=aaa")

    def test_parse_agenda(self):
        """日程表列：摘要PDF、會議紀錄、審查會清單與議事錄皆能取得。"""
        html = """<table><tr><th>日期</th></tr>
        <tr><td>115-08-05</td><td>三</td><td>2</td><td>委員會</td><td>業務質詢</td><td></td><td></td><td></td>
          <td><p><a href="https://ntpbook.ntp.gov.tw/Mam/x.pdf">摘要紀錄</a></p></td>
          <td><a href="/Home/BookAgenda/ViewRecord?cBookAgendaID=r1">會議紀錄</a></td><td></td></tr>
        <tr><td>115-08-14</td><td>五</td><td></td><td>委員會</td><td>委員會</td>
          <td><a href="/Home/BookAgenda/ViewExamAnnex?bookAgendaID=e1">會議紀錄&nbsp;<span>5</span></a></td>
          <td><a href="/Home/BookAgenda/ViewExamRecord?bookAgendaID=e1&amp;examId=05&amp;examName=%E7%AC%AC5%E5%AF%A9%E6%9F%A5%E5%A7%94%E5%93%A1%E6%9C%83">第5審查委員會</a></td>
          <td><a href="/Home/ExamVideo?bookAgendaID=e1&amp;examId=05">第5審查委員會</a></td><td></td><td></td><td></td><td></td></tr>
        </table>"""
        rows = AgendaPageParser.parse_agenda(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].summary_pdf_url, "https://ntpbook.ntp.gov.tw/Mam/x.pdf")
        self.assertTrue(rows[0].record_url.endswith("cBookAgendaID=r1"))
        self.assertEqual(rows[0].pm_agenda, "業務質詢")
        self.assertIsNone(rows[1].summary_pdf_url)
        self.assertTrue(rows[1].exam_annex_url.endswith("bookAgendaID=e1"))
        self.assertEqual(len(rows[1].exam_records), 1)
        self.assertEqual(rows[1].exam_records[0].exam_id, "05")
        self.assertEqual(rows[1].exam_records[0].exam_name, "第5審查委員會")

    def test_parse_exam_annex(self):
        """審查會紀錄清單頁：取得 PDF 標題與網址。"""
        html = """<a href="https://ntpbook.ntp.gov.tw/Mam/a.pdf" target="_blank" class="list-group-item">
            <p class="list-group-item-text">1150814第5審查會會議紀錄</p></a>
            <a href="/Home">首頁</a>"""
        links = AgendaPageParser.parse_exam_annex(html)
        self.assertEqual([(l.title, l.url) for l in links],
                         [("1150814第5審查會會議紀錄", "https://ntpbook.ntp.gov.tw/Mam/a.pdf")])

    def test_ssl_context_keeps_verification(self):
        """SSL 設定仍須驗證憑證與主機名稱。"""
        import ssl
        ctx = build_ssl_context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
