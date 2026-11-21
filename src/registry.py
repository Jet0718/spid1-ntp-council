"""第四屆市議員標準名冊與姓名正規化模組。

職責（單一職責原則）：
1. 維護市議員標準姓名與別名（原住民議員中文名、不同標點寫法）的對應。
2. 從「出席／請假」欄位文字切分出議員姓名。
3. 將逐字稿發言者標籤（如「陳議員偉杰：」）還原成議員標準姓名。
4. 在摘要紀錄全文中找出以「○議員○○」形式被提及的議員。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple

# 中日韓漢字範圍（含擴充 A 區，涵蓋「䕒」等罕用字）
CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
# 原住民姓名中間點的各種寫法，統一轉成「‧」(U+2027)
_DOT_PATTERN = re.compile(r"\s*[．‧・·•\.]\s*")
# 切分姓名用：連續漢字，或以中間點串接的拉丁字母名
_TOKEN_PATTERN = re.compile(rf"[{CJK}]+|[A-Za-z]+(?:‧[A-Za-z]+)*")
# 純漢字判斷
_CJK_ONLY = re.compile(rf"^[{CJK}]+$")
# 發言者標籤：前綴 + 職稱 + 後綴，例如「陳議員偉杰」「李翁議員月娥」「宋雨蓁Nikar‧Falong議員」
_SPEAKER_PATTERN = re.compile(r"^(.+?)(議員|副召集人|召集人|委員)(.*)$")

# 第四屆議員席次表（第8次定期會版本）中的 64 位議員，作為種子名冊
SEED_COUNCILORS: Tuple[str, ...] = (
    "蔣根煌", "陳鴻源", "陳偉杰", "金瑞龍", "林國春", "呂家愷", "鄭宇恩", "張嘉玲",
    "戴瑋姗", "顏蔚慈", "曾煥嘉", "黃永昌", "黃桂蘭", "王威元", "江怡臻", "彭佳芸",
    "鍾宏仁", "廖宜琨", "林秉宥", "張錦豪", "洪佳君", "陳儀君", "白珮茹", "蔡淑君",
    "陳錦錠", "黃淑君", "李宇翔", "石一佑", "邱婷蔚", "陳家琪", "楊春妹", "連斐璠",
    "劉美芳", "李翁月娥", "蘇錦雄Paylang‧Caya", "林銘仁", "卓冠廷", "翁震州", "陳啟能",
    "蔡健棠", "林金結", "邱烽堯", "劉哲彰", "陳世軒", "馬見Lahuy‧Ipin", "陳乃瑜",
    "山田摩衣", "陳永福", "李倩萍", "游輝宂", "黃心華", "戴湘儀", "陳明義", "蘇泓欽",
    "彭一書", "張維倩", "許昭興", "林裔綺", "宋明宗", "周勝考", "蔡錦賢",
    "宋雨蓁Nikar‧Falong", "周雅玲", "李余典",
)

# 出席／請假欄位中不是姓名的常見字詞
_STOP_TOKENS = {"無", "詳如簽到簿", "如簽到簿", "詳簽到簿", "簽到簿", "均出席", "全體出席", "公假", "事假", "病假", "喪假"}
# 自動補入名冊時，含有這些字詞的候選一律排除（避免職稱被誤認為姓名）
_NON_NAME_HINTS = ("議員", "議長", "局長", "處長", "主任", "秘書", "委員", "簽到", "專門",
                   "召集", "市長", "主委", "代理", "人員", "記錄", "紀錄", "假", "出席", "請假")


def normalize_text(text: str) -> str:
    """統一原住民姓名中間點寫法並移除多餘空白。

    Args:
        text: 原始文字
    Returns:
        中間點統一為「‧」、全形空白轉為半形的文字
    """
    text = text.replace("\u3000", " ")
    return _DOT_PATTERN.sub("‧", text)


def compact(text: str) -> str:
    """正規化後再移除所有空白，用於子字串比對。"""
    return re.sub(r"\s+", "", normalize_text(text))


class CouncilorRegistry:
    """市議員標準名冊。

    以種子名冊初始化，可再透過 discover() 從實際紀錄中自動補入離職或補選議員。
    """

    def __init__(self, seed: Iterable[str] = SEED_COUNCILORS) -> None:
        """建立名冊。

        Args:
            seed: 初始議員標準姓名清單
        """
        self._canonical: Set[str] = set()  # 標準姓名集合
        self._alias: Dict[str, str] = {}  # 別名（已 compact）→ 標準姓名
        self._mention_forms: Dict[str, List[str]] = {}  # 標準姓名 → 「○議員○○」等提及形式
        for name in seed:
            self.register(name)

    # ------------------------------------------------------------------ 名冊維護
    @staticmethod
    def chinese_part(name: str) -> str:
        """取得姓名開頭的漢字部分（原住民議員為中文名）。"""
        m = re.match(rf"[{CJK}]+", name)
        return m.group(0) if m else name

    def register(self, name: str) -> str:
        """將議員加入名冊並建立別名與提及形式。

        Args:
            name: 議員姓名（可含原住民羅馬拼音）
        Returns:
            正規化後的標準姓名
        """
        canonical = compact(name)
        if canonical in self._canonical:
            return canonical
        self._canonical.add(canonical)
        self._alias[canonical] = canonical
        zh = self.chinese_part(canonical)
        # 原住民議員常只寫中文名，例如「馬見」
        if zh != canonical and zh not in self._alias:
            self._alias[zh] = canonical
        forms: List[str] = []
        for title in ("議員", "委員"):
            # 姓氏可能為 1 或 2 字（如「李翁」），兩種切法都產生
            for k in (1, 2):
                if len(zh) - k >= 1:
                    forms.append(zh[:k] + title + zh[k:])
            forms.append(canonical + title)
            if zh != canonical:
                forms.append(zh + title)
        self._mention_forms[canonical] = forms
        return canonical

    @property
    def names(self) -> List[str]:
        """回傳排序後的全部標準姓名。"""
        return sorted(self._canonical)

    def normalize_name(self, raw: str) -> Optional[str]:
        """把任意寫法的姓名對應到標準姓名，找不到回傳 None。"""
        return self._alias.get(compact(raw))

    # ------------------------------------------------------------------ 欄位切分
    def tokenize_block(self, text: str) -> List[str]:
        """把出席／請假欄位文字切成姓名候選字串。

        拉丁字母部分會併入前一個漢字字串，例如「馬見 Lahuy．Ipin」→「馬見Lahuy‧Ipin」。
        """
        tokens: List[str] = []
        for tok in _TOKEN_PATTERN.findall(normalize_text(text)):
            is_latin = not _CJK_ONLY.match(tok)
            if is_latin and tokens:
                tokens[-1] = tokens[-1] + tok  # 拉丁拼音接在前一個姓名後
            else:
                tokens.append(tok)
        return [t for t in tokens if t not in _STOP_TOKENS]

    def _segment(self, token: str) -> Tuple[List[str], List[str]]:
        """用名冊對黏在一起的姓名字串做最長比對切分。

        Returns:
            (已辨識之標準姓名清單, 無法辨識的片段清單)
        """
        found: List[str] = []
        unknown: List[str] = []
        i, buf = 0, ""
        while i < len(token):
            match = None
            for j in range(len(token), i + 1, -1):  # 由長到短嘗試
                cand = token[i:j]
                if cand in self._alias:
                    match = (self._alias[cand], j)
                    break
            if match:
                if buf:
                    unknown.append(buf)
                    buf = ""
                found.append(match[0])
                i = match[1]
            else:
                buf += token[i]
                i += 1
        if buf:
            unknown.append(buf)
        return found, unknown

    def extract_from_block(self, text: Optional[str]) -> Tuple[Set[str], List[str]]:
        """從出席／請假欄位抽出議員。

        Args:
            text: 欄位原始文字
        Returns:
            (辨識出的標準姓名集合, 無法辨識的候選字串清單)
        """
        if not text:
            return set(), []
        found: Set[str] = set()
        unknown: List[str] = []
        for tok in self.tokenize_block(text):
            if tok in self._alias:
                found.add(self._alias[tok])
                continue
            names, rest = self._segment(tok)
            found.update(names)
            unknown.extend(r for r in rest if len(r) >= 2)
        return found, unknown

    # ------------------------------------------------------------------ 發言者 / 提及
    def extract_councilor_from_speaker(self, label: str) -> Optional[str]:
        """把逐字稿發言者標籤還原為議員標準姓名。

        只接受「議員／委員／召集人」職稱且能對應到名冊者；
        主席、議長主持發言及官員一律回傳 None。
        """
        clean = compact(label).rstrip("：:")
        m = _SPEAKER_PATTERN.match(clean)
        if not m:
            return None
        prefix, _, suffix = m.groups()
        for cand in (prefix + suffix, prefix):
            if cand and cand in self._alias:
                return self._alias[cand]
        return None

    @staticmethod
    def speaker_candidate(label: str) -> Optional[str]:
        """取出「○議員○○」標籤中的候選姓名（供自動補入名冊用）。"""
        clean = compact(label).rstrip("：:")
        m = re.match(rf"^([{CJK}]{{1,2}})議員([{CJK}]{{1,3}})$", clean)
        if m:
            return m.group(1) + m.group(2)
        return None

    def find_mentions(self, text: str) -> Set[str]:
        """在文字中找出以「○議員○○」「○○○議員」形式被提及的議員。"""
        flat = compact(text)
        found: Set[str] = set()
        for name, forms in self._mention_forms.items():
            if any(f in flat for f in forms):
                found.add(name)
        return found

    # ------------------------------------------------------------------ 自動補入
    def discover(self, candidates: Iterable[str], min_count: int = 2) -> List[str]:
        """從無法辨識的候選字串中，把出現次數足夠的姓名補入名冊。

        Args:
            candidates: 候選姓名（可重複，用於計數）
            min_count: 最少出現次數
        Returns:
            新補入的標準姓名清單
        """
        counter = Counter(compact(c) for c in candidates)
        added: List[str] = []
        for cand, cnt in counter.most_common():
            zh = self.chinese_part(cand)
            if cnt < min_count or not (2 <= len(zh) <= 4):
                continue
            if any(h in cand for h in _NON_NAME_HINTS) or cand in self._alias:
                continue
            added.append(self.register(cand))
        return added
