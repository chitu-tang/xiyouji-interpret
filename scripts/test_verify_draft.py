#!/usr/bin/env python3
"""Unit tests for scripts/verify_draft.py."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_draft as vd


SAMPLE_SOURCE = (
    "众猴拍手称扬道：“好水！好水！原来此处远通山脚之下，直接大海之波。”"
    "又道：“哪一个有本事的，钻进去寻个源头出来，不伤身体者，我等即拜他为王。”"
    "连呼了三声，忽见丛杂中跳出一个石猴，应声高叫道：“我进去！我进去！”"
)


class TestVerifyDraft(unittest.TestCase):
    def test_count_hanzi_cjk_only(self) -> None:
        self.assertEqual(vd.count_hanzi("你好，朋友！ABC123——"), 4)

    def test_quote_exact_sentence_and_short_phrase(self) -> None:
        draft = (
            "这里写了“好水！好水！”两个感叹，还说了“寻个源头”和“不伤身体者”，"
            "最后整句是“原来此处远通山脚之下，直接大海之波。”"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertEqual(rep.quote_failures, [])
        self.assertEqual(rep.quote_total, 4)

    def test_quote_missing_ellipsis_fails(self) -> None:
        # 10 chars truncated mid-sentence without trailing ellipsis
        draft = "原文提到“原来此处远通山脚之下”，这里还没说完。"
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertEqual(len(rep.quote_failures), 1)
        self.assertEqual(rep.quote_failures[0].status, "MISSING_TRAILING_ELLIPSIS")

    def test_quote_proper_excerpt_passes(self) -> None:
        draft = (
            "原文写道“原来此处远通山脚之下……”以及“……钻进去寻个源头出来……”"
            "还有跨段节引“哪一个有本事的……我等即拜他为王。”"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertEqual(rep.quote_failures, [])

    def test_quote_concept_label_or_out_of_scope_fails(self) -> None:
        draft = "这就是所谓的“契约选王”，后来他还去了“水帘洞”。"
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertEqual(len(rep.quote_failures), 2)
        self.assertTrue(all(f.status == "NOT_IN_SOURCE" for f in rep.quote_failures))

    def test_negative_contrast_limit_0_to_1_per_1000(self) -> None:
        filler = "这段文字推进得非常扎实，每个动作都在把人物往前推。" * 45  # ~1000 hanzi
        ok_draft = filler + "这事不是拍脑袋，而是有步步铺垫。"
        rep_ok = vd.verify_draft(SAMPLE_SOURCE, ok_draft, genre="article", min_hanzi=0, max_hanzi=0)
        self.assertTrue(rep_ok.passed, rep_ok.hard_errors)

        bad_draft = ok_draft + "它也不在胆子大，而在眼力准。"
        rep_bad = vd.verify_draft(SAMPLE_SOURCE, bad_draft, genre="article", min_hanzi=0, max_hanzi=0)
        self.assertFalse(rep_bad.passed)
        self.assertTrue(any("否定对照句式超限" in e for e in rep_bad.hard_errors))

    def test_punctuation_excludes_verbatim_quotes(self) -> None:
        # Source quote has 2 exclamation marks; narrator has 1 -> total narrator exclam = 1 (PASS)
        draft = "原文高喊“我进去！我进去！”真干脆！"
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="article", min_hanzi=0, max_hanzi=0)
        self.assertEqual(rep.metrics["exclam_count"], 1)
        self.assertTrue(rep.passed, rep.hard_errors)

    def test_spoken_structure_and_length(self) -> None:
        body_core = "众猴在瀑布外头看热闹，连喊了三声没人动弹，石猴直接跳出来应声。" * 35  # ~1015 hanzi
        deliverable = (
            "## 原文核验与解读边界\n"
            "- 分析范围：所给片段\n\n"
            "## 口播正文\n\n"
            "“我进去！我进去！”\n\n"
            "你好，朋友。今天我们来聊石猴怎么应声。\n\n"
            f"{body_core}\n\n"
            "好，今天我们就聊到这里。\n\n"
            "## 研究说明\n"
            "- 本稿以纯文本细读为主。\n"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, deliverable, genre="spoken", min_hanzi=1000, max_hanzi=1200)
        self.assertTrue(rep.passed, rep.hard_errors)

    def test_spoken_missing_hook_before_intro_fails(self) -> None:
        deliverable = (
            "## 口播正文\n\n"
            "你好，朋友。今天我们来聊石猴。\n\n"
            "正文内容。\n\n"
            "好，今天我们就聊到这里。\n"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, deliverable, genre="spoken", min_hanzi=0, max_hanzi=0)
        self.assertFalse(rep.passed)
        self.assertTrue(any("缺少钩子" in e for e in rep.hard_errors))

    def test_quote_missing_only_trailing_period_is_not_truncation(self) -> None:
        draft = "原句是“原来此处远通山脚之下，直接大海之波”，收在海波上。"
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertEqual(rep.quote_failures, [])

    def test_short_quote_with_comma_still_requires_ellipsis(self) -> None:
        # 7 hanzi but contains comma -> NOT exempted by short-phrase rule; truncated on right!
        draft = "原文写“连呼了三声，忽见”，说明速度很快。"
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertEqual(len(rep.quote_failures), 1)
        self.assertEqual(rep.quote_failures[0].status, "MISSING_TRAILING_ELLIPSIS")

    def test_shibushi_not_false_positive_for_negative_contrast(self) -> None:
        draft = "这是不是勇气，是个值得追问的地方。这回不再含糊，直接看动作。"
        rep = vd.verify_draft(SAMPLE_SOURCE, draft, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertEqual(rep.metrics["negative_contrast"], 0)

    def test_hook_with_quoted_exclamations_counts_as_single_unit(self) -> None:
        deliverable = (
            "## 口播正文\n\n"
            "“好水！好水！原来此处远通山脚之下，直接大海之波。”\n\n"
            "众猴拍手称好，接着立了规矩，谁敢钻进去找源头就拜谁为王。\n\n"
            "“我进去！我进去！”\n\n"
            "你好，朋友。今天我们来聊石猴怎么应声。\n\n"
            "好，今天我们就聊到这里。\n"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, deliverable, genre="spoken", min_hanzi=0, max_hanzi=0)
        self.assertTrue(rep.passed, rep.hard_errors)

    def test_genre_none_skips_prose_punctuation_limits_for_candidate_cards(self) -> None:
        card = (
            "## 原文核验\n"
            "- 出处与版本：测试\n"
            "- 本次分析范围：测试\n"
            "- 核验状态：部分确认\n"
            "- 角度一——从“连呼了三声”到“应声高叫”——测试——再来一个\n"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, card, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertTrue(rep.passed, rep.hard_errors)
        self.assertEqual(rep.warnings, [])

    def test_sop_leak_and_overquoting_warnings_in_spoken_mode(self) -> None:
        quotes_spam = " ".join(["“好水”"] * 11)
        deliverable = (
            "## 口播正文\n\n"
            "“我进去！我进去！”\n\n"
            "你好，朋友。今天我们来聊石猴。\n\n"
            f"{quotes_spam}\n"
            "这个朴素解释我认账，咱不翻后账。\n\n"
            "好，今天我们就聊到这里。\n"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, deliverable, genre="spoken", min_hanzi=0, max_hanzi=0)
        self.assertTrue(any("规则/评测穿帮词" in w for w in rep.warnings), rep.warnings)
        self.assertTrue(any("直接引号偏密" in w for w in rep.warnings), rep.warnings)

    def test_v32_repetitive_substitutes_linear_walkthrough_and_text_fence_quotes(self) -> None:
        deliverable = (
            "## 口播正文\n\n"
            "“我进去！我进去！”\n\n"
            "你好，朋友。今天我们来聊石猴。\n\n"
            "往下看两句，却发现他却没走，却停在原地，却又跳了出来。\n"
            "真正厉害的是胆识，真正难得的是眼力，真正动人的是速度。\n"
            "回到字面上看并非如此。回到原文就能拦住这种误读。\n\n"
            "好，今天我们就聊到这里。\n"
        )
        rep = vd.verify_draft(SAMPLE_SOURCE, deliverable, genre="spoken", min_hanzi=0, max_hanzi=0)
        self.assertTrue(any("顺句串讲过渡词" in w for w in rep.warnings), rep.warnings)
        self.assertTrue(any("“却”偏密" in w for w in rep.warnings), rep.warnings)
        self.assertTrue(any("“真正”复读偏密" in w for w in rep.warnings), rep.warnings)
        self.assertTrue(any("边界回拉句式同构重复" in w for w in rep.warnings), rep.warnings)

        # Quotes inside ```text blocks (like P4 frameworks) MUST still be verified!
        framework = "```text\n主轴：看看“不存在的伪引文”怎么讲。\n```\n"
        rep_fw = vd.verify_draft(SAMPLE_SOURCE, framework, genre="none", min_hanzi=0, max_hanzi=0)
        self.assertFalse(rep_fw.passed)
        self.assertEqual(rep_fw.quote_failures[0].status, "NOT_IN_SOURCE")


if __name__ == "__main__":
    unittest.main()
