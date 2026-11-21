# 新北市議會第四屆議員出席與質詢統計工具 (readme.md)

## 專案簡介
本工具能自動檢索**新北市議會議事錄檢索系統**（`https://ntpbook.ntp.gov.tw/Home/Home/IndexByMJ`）中**第四屆所有會期會議**（包含定期會、臨時會、成立大會共 19 個會期），下載並解析各場次之「大會摘要紀錄（PDF）」、「大會會議紀錄（HTML逐字稿）」、「審查會會議紀錄（PDF）」與「審查會議事錄（HTML逐字稿）」。

系統僅針對**新北市第四屆市議員**（自動過濾列席官員與行政人員）提取其**出席名單**、**請假名單**與**質詢（發言）名單**，並輸出完整的 Excel 統計報表（包含「議員出席與質詢總統計表」及「各場次會議明細表」）。

## 專案結構
```text
c:\TEST\spid1\
├── gemini.md                  # AI 開發規範與專案指引
├── spec.md                    # 系統規格書 (含 Mermaid 架構、流程、序列、狀態、ER、類別圖與虛擬碼)
├── readme.md                  # 專案使用說明文件
├── requirements.txt           # Python 套件相依清單
├── main.py                    # 程式主進入點 (CLI)
├── src/
│   ├── __init__.py
│   ├── models.py              # 資料模型定義 (SessionInfo, MeetingRecord, CouncilorStats)
│   ├── registry.py            # 第四屆市議員標準名冊與姓名正規化模組
│   ├── crawler.py             # 議事錄網站爬蟲與本地快取管理模組
│   ├── pdf_parser.py          # 摘要紀錄與審查會會議紀錄 PDF 解析器
│   ├── html_parser.py         # 大會會議紀錄與審查會議事錄 HTML 解析器
│   ├── aggregator.py          # 出席率與質詢率統計計算引擎
│   ├── exporter.py            # Excel 報表匯出器
│   └── orchestrator.py        # 整體檢索、解析與匯出流程協調器
└── tests/                     # 單元測試目錄
    ├── __init__.py
    ├── test_registry.py       # 議員名冊與正規化單元測試
    ├── test_parsers.py        # PDF 與 HTML 解析器單元測試
    └── test_aggregator.py     # 出席率與質詢率統計計算與 Excel 匯出單元測試
```

## 環境需求與安裝
1. Python 3.10 以上版本（Windows 環境）
2. 安裝相依套件：
   ```powershell
   pip install -r requirements.txt
   ```

## 使用方式
1. **執行完整第四屆所有會期檢索與匯出 Excel**：
   ```powershell
   python main.py --output "新北市議會第4屆議員出席與質詢統計表.xlsx"
   ```
2. **指定特定會期關鍵字進行檢索（例如僅檢索第8次定期會）**：
   ```powershell
   python main.py --session-filter "第8次定期會" --output "第8次定期會統計表.xlsx"
   ```
3. **執行單元測試**：
   ```powershell
   python -m unittest discover -s tests -v
   ```
