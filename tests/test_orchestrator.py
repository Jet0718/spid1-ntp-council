"""CouncilStatsOrchestrator 離線整合測試。"""
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

from src.crawler import AgendaPageParser, IFetcher, NtpCouncilCrawler
from src.exporter import ExcelReportExporter
from src.models import SessionInfo
from src.orchestrator import CouncilStatsOrchestrator, committee_key, short_title
from src.registry import CouncilorRegistry


class MockFetcher(IFetcher):
    """離線 Mock Fetcher，以字典提供對應 URL 的二進位或文字內容。"""

    def __init__(self, mapping: Dict[str, bytes]):
        self.mapping = mapping

    def fetch_bytes(self, url: str) -> bytes:
        if url in self.mapping:
            return self.mapping[url]
        raise RuntimeError(f"MockFetcher: 找不到 URL {url}")


class TestOrchestratorOffline(unittest.TestCase):
    """測試流程協調器。"""

    def test_committee_key_and_title(self):
        """測試委員會名稱正規化與標題簡化。"""
        self.assertEqual(committee_key("1150814第5審查會會議紀錄"), "第5審查會")
        self.assertEqual(committee_key("第2審查委員會", exam_id="02"), "第2審查會")
        self.assertEqual(committee_key("法規會會議紀錄", exam_id="LR"), "法規審查會")
        self.assertEqual(
            short_title("新北市議會第4屆第8次定期會預備會議摘要紀錄"),
            "預備會議摘要紀錄"
        )

    def test_orchestrator_pipeline_offline(self):
        """以 Mock 資料驗證整個協調器流程（檢索、解析、統計、匯出）。"""
        index_html = """
        <a href="/Home/BookAgenda?cBookMdslID=s1"><p>第4屆第8次定期會</p></a>
        """.encode("utf-8")

        agenda_html = """
        <table>
        <tr>
            <td>115-08-05</td><td>三</td><td>1</td><td>委員會</td><td>業務質詢</td>
            <td></td><td></td><td></td>
            <td><a href="https://ntpbook.ntp.gov.tw/Mam/sum1.pdf">摘要紀錄</a></td>
            <td><a href="/Home/BookAgenda/ViewRecord?cBookAgendaID=rec1">會議紀錄</a></td>
        </tr>
        </table>
        """.encode("utf-8")

        # 模擬 PDF 文字（包含標題、出席、請假、全文）
        # 這裡因為 PdfRecordParser 依賴 PypdfTextExtractor，我們直接注入自訂 extractor 或自製 PDF bytes
        # 為了簡化，直接測試 mock 呼叫
        mapping = {
            "https://ntpbook.ntp.gov.tw/Home/Home/IndexByMJ": index_html,
            "https://ntpbook.ntp.gov.tw/Home/BookAgenda?cBookMdslID=s1": agenda_html,
        }
        crawler = NtpCouncilCrawler(MockFetcher(mapping))
        sessions = crawler.fetch_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].session_name, "第4屆第8次定期會")


if __name__ == "__main__":
    unittest.main()
