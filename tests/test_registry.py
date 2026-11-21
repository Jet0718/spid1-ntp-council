"""CouncilorRegistry 議員名冊與姓名正規化單元測試。"""
import unittest

from src.registry import CouncilorRegistry, compact, normalize_text


class TestNormalize(unittest.TestCase):
    """測試文字正規化函式。"""

    def test_dot_variants_unified(self):
        """各種中間點寫法都應統一為「‧」。"""
        self.assertEqual(compact("馬見 Lahuy．Ipin"), "馬見Lahuy‧Ipin")
        self.assertEqual(compact("馬見Lahuy・Ipin"), "馬見Lahuy‧Ipin")
        self.assertEqual(normalize_text("Nikar ‧ Falong"), "Nikar‧Falong")


class TestRegistry(unittest.TestCase):
    """測試名冊對應、欄位切分、發言者辨識與提及比對。"""

    def setUp(self):
        """每個測試使用全新的種子名冊。"""
        self.reg = CouncilorRegistry()

    def test_normalize_aboriginal_aliases(self):
        """原住民議員全名、中文名皆對應到同一標準姓名。"""
        self.assertEqual(self.reg.normalize_name("馬見 Lahuy．Ipin"), "馬見Lahuy‧Ipin")
        self.assertEqual(self.reg.normalize_name("馬見"), "馬見Lahuy‧Ipin")
        self.assertIsNone(self.reg.normalize_name("侯友宜"))

    def test_extract_block_basic(self):
        """出席欄位含換行與原住民姓名時應正確切分。"""
        text = "金瑞龍  曾煥嘉  馬見 Lahuy．Ipin \n陳儀君  石一佑  蘇錦雄 Paylang．Caya \n宋雨蓁 Nikar．\nFalong"
        found, unknown = self.reg.extract_from_block(text)
        self.assertEqual(found, {"金瑞龍", "曾煥嘉", "馬見Lahuy‧Ipin", "陳儀君", "石一佑",
                                 "蘇錦雄Paylang‧Caya", "宋雨蓁Nikar‧Falong"})
        self.assertEqual(unknown, [])

    def test_extract_block_concatenated_and_unknown(self):
        """黏在一起的姓名以名冊切分；不在名冊者列為未知候選。"""
        found, unknown = self.reg.extract_from_block("山田摩衣林裔綺 葉元之")
        self.assertEqual(found, {"山田摩衣", "林裔綺"})
        self.assertEqual(unknown, ["葉元之"])

    def test_extract_block_sign_in_and_none(self):
        """「詳如簽到簿」「無」不應被當成姓名。"""
        self.assertEqual(self.reg.extract_from_block("詳如簽到簿"), (set(), []))
        self.assertEqual(self.reg.extract_from_block("無"), (set(), []))
        self.assertEqual(self.reg.extract_from_block(None), (set(), []))

    def test_speaker_labels(self):
        """發言者標籤：議員／委員／召集人可辨識；主席、官員、專門委員不算。"""
        f = self.reg.extract_councilor_from_speaker
        self.assertEqual(f("陳議員偉杰："), "陳偉杰")
        self.assertEqual(f("李翁議員月娥："), "李翁月娥")
        self.assertEqual(f("宋雨蓁Nikar．Falong議員："), "宋雨蓁Nikar‧Falong")
        self.assertEqual(f("陳委員儀君："), "陳儀君")
        self.assertEqual(f("李召集人余典："), "李余典")
        self.assertIsNone(f("主\u3000\u3000\u3000席："))
        self.assertIsNone(f("劉副市長和然："))
        self.assertIsNone(f("徐專門委員綺櫻："))
        self.assertIsNone(f("林瑋茜Siku Yaway局長："))

    def test_find_mentions(self):
        """摘要紀錄中「○議員○○」及原住民「全名+議員」形式皆可找到。"""
        text = ("有陳議員偉杰、呂議員家愷、宋雨蓁Nikar．Falong 議員\n、蔡議員錦賢等提出多項問題，"
                "經劉副市長和然予以說明。十八、黃議員淑\n君要求：")
        self.assertEqual(self.reg.find_mentions(text),
                         {"陳偉杰", "呂家愷", "宋雨蓁Nikar‧Falong", "蔡錦賢", "黃淑君"})

    def test_discover_threshold_and_filter(self):
        """自動補入：次數不足或含職稱字詞者不補入。"""
        added = self.reg.discover(["葉元之", "葉元之", "廖先翔", "議員", "議員", "秘書長甲", "秘書長甲"])
        self.assertEqual(added, ["葉元之"])
        self.assertEqual(self.reg.normalize_name("葉元之"), "葉元之")
        self.assertEqual(self.reg.extract_councilor_from_speaker("葉議員元之："), "葉元之")

    def test_speaker_candidate(self):
        """未在名冊的「○議員○○」標籤可取出候選姓名。"""
        self.assertEqual(CouncilorRegistry.speaker_candidate("葉議員元之："), "葉元之")
        self.assertIsNone(CouncilorRegistry.speaker_candidate("方局長仰寧："))


if __name__ == "__main__":
    unittest.main()
