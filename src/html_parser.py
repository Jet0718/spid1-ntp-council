"""大會會議紀錄與審查會議事錄（HTML 逐字稿）解析器。

職責：從逐字稿頁面取出依序出現的發言者標籤（例如「陳議員偉杰：」）。
是否為市議員由 CouncilorRegistry 判斷（單一職責原則）。
"""
from __future__ import annotations

from collections import Counter

from bs4 import BeautifulSoup


class HtmlTranscriptParser:
    """逐字稿頁面解析器。

    網站逐字稿結構為表格：左欄 `<td valign="top">發言者：</td>`，右欄為發言內容。
    """

    def parse_speakers(self, html_text: str) -> Counter:
        """取出所有發言者標籤及其發言段落數。

        Args:
            html_text: 逐字稿頁面 HTML
        Returns:
            Counter，鍵為發言者標籤（已去除空白），值為段落數
        """
        soup = BeautifulSoup(html_text, "html.parser")
        speakers: Counter = Counter()
        for td in soup.find_all("td", attrs={"valign": "top"}):
            label = "".join(td.get_text().split())  # 移除全形與半形空白
            if label.endswith(("：", ":")) and len(label) > 1:
                speakers[label] += 1
        return speakers
