"""新北市議會第四屆議員出席與質詢統計工具 - 命令列進入點。

用法範例：
    python main.py
    python main.py --session-filter 第8次定期會 --output 第8次定期會統計表.xlsx
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.crawler import HttpFetcher, NtpCouncilCrawler
from src.exporter import ExcelReportExporter
from src.orchestrator import CouncilStatsOrchestrator
from src.registry import CouncilorRegistry


def parse_args(argv=None) -> argparse.Namespace:
    """解析命令列參數。"""
    p = argparse.ArgumentParser(description="新北市議會議員出席與質詢統計")
    p.add_argument("--output", default="新北市議會第4屆議員出席與質詢統計表.xlsx", help="Excel 輸出路徑")
    p.add_argument("--term", default="第4屆", help="屆次前綴（預設：第4屆）")
    p.add_argument("--session-filter", action="append", default=[],
                   help="只處理名稱包含此關鍵字的會期，可重複指定")
    p.add_argument("--workers", type=int, default=8, help="並行下載執行緒數")
    p.add_argument("--cache-dir", default=".cache", help="下載快取目錄")
    p.add_argument("--no-cache", action="store_true", help="忽略既有快取，重新下載")
    p.add_argument("-v", "--verbose", action="store_true", help="顯示詳細記錄")
    return p.parse_args(argv)


def main(argv=None) -> int:
    """組裝各元件並執行統計流程。"""
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    fetcher = HttpFetcher(cache_dir=Path(args.cache_dir), use_cache=not args.no_cache)
    orchestrator = CouncilStatsOrchestrator(
        crawler=NtpCouncilCrawler(fetcher), registry=CouncilorRegistry(),
        exporter=ExcelReportExporter(), workers=args.workers)
    s = orchestrator.run(Path(args.output), args.session_filter, args.term)

    print("\n===== 執行完成 =====")
    print(f"會期數：{len(s.sessions)}")
    print(f"有效會議場次：{s.meetings}（大會 {s.plenary}、審查會 {s.committee}），略過 {s.skipped}")
    print(f"簽到簿場次：{s.sign_in_meetings}；掃描 PDF：{s.scanned_pdfs}；下載失敗：{len(s.failed_urls)}")
    print(f"統計議員人數：{s.councilors}；自動補入名冊：{'、'.join(s.discovered) or '無'}")
    print(f"輸出檔案：{s.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
