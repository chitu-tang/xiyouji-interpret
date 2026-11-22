#!/usr/bin/env python3
"""Deterministic verifier for xiyouji-interpret drafts and deliverables.

Zero external dependencies (Python 3.9+ stdlib only).
Checks:
  1. Hanzi length count (Unicode CJK Unified Ideographs U+4E00-U+9FFF, aligned with xiyouji-deep-read).
  2. Quote fidelity & scope lock: every paired quote in the deliverable must match the
     user-provided source text (or optional user message) verbatim, with strict ellipsis
     rules for excerpts and short-phrase exemptions (<8 non-punct chars without internal punct).
  3. Hard style/forbidden rules on narrator prose (excluding direct quotes):
     - Forbidden phrases (0 tolerance)
     - Negative contrast constructions (0-1 per 1000 narrator hanzi)
     - "但/但是" density (<= 1 per 1000 narrator hanzi)
     - Punctuation limits: "——" <= 2, "：" <= 3, "！" <= 1
  4. Spoken script structural markers (when --genre spoken):
     - Hook (1-5 sentences) before fixed intro "你好，朋友。今天我们来聊"
     - Fixed outro "好，今天我们就聊到这里。" as the final line of the body
  5. Soft / Tier-1 & Tier-3 warnings: AI high-frequency words, filler transitions,
     ordinal enumeration, and 3+ consecutive sentences of nearly identical length.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

CLAUSE_BOUNDARIES = set("。！？；“”‘’「」『』\"\n")
SENTENCE_END_PUNCT = set("。！？；")
SHORT_PHRASE_DISALLOWED_PUNCT = set("，。！？：；、")
PUNCT_AND_SPACE = set(
    " \t\r\n，。！？：；、…“”‘’「」『』—-·（）()《》〈〉【】[]\"'.,!?;:"
)

QUOTE_PAIRS: Dict[str, str] = {
    "“": "”",
    "‘": "’",
    "「": "」",
    "『": "』",
}

FORBIDDEN_PHRASE_PATTERNS: List[Tuple[str, str]] = [
    ("最让我停下来想的一章", r"最让我停下来想的一章"),
    ("这话听着软，其实很硬", r"这话听着软[，,]其实很硬"),
    ("有没有过这样的时刻", r"有没有过这样的时刻"),
    ("读到……一句话，愣住了", r"读到[^。！？\n]{0,14}一句话[，,]愣住了"),
    ("里面藏着……", r"里面藏着"),
    ("这里值得停一下", r"这里值得停一下"),
    ("这句话让我想了好久", r"这句话让我想了好久"),
    ("……没变，……没变，变的是……", r"没变[^。！？\n]{1,30}没变[^。！？\n]{1,30}变的是"),
]

NEGATIVE_CONTRAST_REGEX = re.compile(
    r"(?<!是)不是[^。！？\n]{1,35}而是"
    r"|(?<!是)不是[^。！？\n]{1,25}[，,]是(?!否)"
    r"|不在于?[^。！？\n]{1,25}而在"
    r"|不仅(?:仅)?[^。！？\n]{1,30}更(?:是)?"
    r"|并非[^。！？\n]{1,30}而是"
)

AI_WARNING_PATTERNS: List[Tuple[str, str]] = [
    ("AI高频词", r"此外|至关重要|深入探讨|彰显|凸显|不可磨灭|深深植根于|蓬勃发展|不断演变|织锦"),
    ("填充式过渡", r"值得注意的是|需要指出的是|有趣的是|总而言之|综上所述|由此可见"),
    ("模糊归因", r"有?学者认为|专家指出|研究表明|研究者普遍指出"),
    ("总结式收尾", r"今天我们学到了|今天我们讲了|从中我们可以得到|这启示我们"),
    ("协作/免责痕迹", r"希望这对您有帮助|如果您想了解更多|由于资料有限|基于目前可获取的信息"),
    (
        "规则/评测穿帮词",
        r"朴素解释|范围锁|不翻后账|不翻片段外|两种(?:容易跑偏的)?现代(?:读法|故事)|再校一遍|按近代汉语用法|顺着这份冷静",
    ),
    ("顺句串讲过渡词", r"往下看(?:两|几)?句|先看开头|先把前头[^。！？\n]{0,10}顺一遍"),
    ("AI自夸式点评短句", r"一句反问[，,]把场面点活了|把场面点活了"),
]

FIXED_INTRO_PREFIX = "你好，朋友。今天我们来聊"
FIXED_OUTRO_EXACT = "好，今天我们就聊到这里。"

# Headings that begin the main spoken or article body when scanning a full deliverable.
BODY_START_HEADINGS = (
    "## 口播正文",
    "## 正文",
    "## 逐段解读",
)

# Headings that end the body section when scanning a full deliverable.
BODY_END_HEADINGS = (
    "## 三审",
    "## 研究",
    "## 下一步",
    "## 核验",
    "## 原文核验",
    "## 交付",
)


@dataclass
class QuoteCheckItem:
    line: int
    quote_char: str
    text: str
    status: str  # EXACT_UNIT | SHORT_PHRASE | EXCERPT_OK | NOT_IN_SOURCE | MISSING_* | UNCLOSED | EMPTY
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status in {"EXACT_UNIT", "SHORT_PHRASE", "EXCERPT_OK"}


@dataclass
class VerificationReport:
    passed: bool
    genre: str
    body_hanzi: int
    narrator_hanzi: int
    min_hanzi: int
    max_hanzi: int
    length_ok: bool
    quote_total: int
    quote_failures: List[QuoteCheckItem] = field(default_factory=list)
    quote_items: List[QuoteCheckItem] = field(default_factory=list)
    hard_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, int] = field(default_factory=dict)


def count_hanzi(text: str) -> int:
    """Count Unicode CJK Unified Ideographs U+4E00-U+9FFF (aligned with xiyouji-deep-read)."""
    return sum(1 for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)


def strip_code_segments(text: str) -> str:
    """Mask executable code blocks and inline code spans while preserving line numbers.

    Plain prose fences like ```text or ```markdown (used for P4 frameworks / templates)
    are intentionally NOT masked so quotes inside frameworks are still verified.
    """
    def _mask_block(match: re.Match) -> str:
        fence_lang = (match.group(1) or "").strip().lower()
        if fence_lang in {"text", "markdown", "md", ""}:
            return match.group(0)
        return "\n" * match.group(0).count("\n")

    cleaned = re.sub(r"```([a-zA-Z0-9_-]*)\n[\s\S]*?```", _mask_block, text)
    cleaned = re.sub(r"`[^`\n]+`", lambda m: " " * len(m.group(0)), cleaned)
    return cleaned


def remove_ignored_sections(text: str, ignored_headings: Sequence[str]) -> str:
    """Mask sections whose H2 heading starts with any prefix in ignored_headings."""
    if not ignored_headings:
        return text
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    ignoring = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            ignoring = any(stripped.startswith(h) for h in ignored_headings)
        if ignoring:
            out.append("\n" if line.endswith("\n") else "")
        else:
            out.append(line)
    return "".join(out)


def extract_body(text: str, genre: str) -> str:
    """Extract the prose body from a structured deliverable, or return full text if bare."""
    start_marker = "<!-- BODY_START -->"
    end_marker = "<!-- BODY_END -->"
    if start_marker in text and end_marker in text:
        s = text.index(start_marker) + len(start_marker)
        e = text.index(end_marker)
        return text[s:e].strip()

    lines = text.splitlines()
    start_idx: Optional[int] = None
    for i, line in enumerate(lines):
        s = line.strip()
        if any(s == h or s.startswith(h + " ") or s.startswith(h + "（") for h in BODY_START_HEADINGS):
            start_idx = i + 1
            break

    if start_idx is None:
        return text.strip()

    collected: List[str] = []
    for line in lines[start_idx:]:
        s = line.strip()
        if s.startswith("## "):
            # In article mode, keep "## 收束" as part of the article body.
            if genre == "article" and s.startswith("## 收束"):
                collected.append(line)
                continue
            if any(s.startswith(h) for h in BODY_END_HEADINGS) or not s.startswith("## 收束"):
                break
        collected.append(line)
    return "\n".join(collected).strip()


def extract_quotes(text: str) -> Tuple[List[Tuple[int, str, str]], List[Tuple[int, str]]]:
    """Extract top-level paired quotes from prose (after masking code blocks).

    Returns (quotes, unclosed_errors), where each quote is (line_no, open_char, inner_text).
    """
    masked = strip_code_segments(text)
    quotes: List[Tuple[int, str, str]] = []
    unclosed: List[Tuple[int, str]] = []

    line = 1
    i = 0
    n = len(masked)
    while i < n:
        ch = masked[i]
        if ch == "\n":
            line += 1
            i += 1
            continue

        # Straight double quote "..."
        if ch == '"':
            start_line = line
            j = i + 1
            inner_chars: List[str] = []
            closed = False
            while j < n:
                cj = masked[j]
                if cj == "\n":
                    line += 1
                if cj == '"':
                    closed = True
                    break
                inner_chars.append(cj)
                j += 1
            if closed:
                quotes.append((start_line, '"', "".join(inner_chars)))
                i = j + 1
            else:
                unclosed.append((start_line, '"'))
                break
            continue

        # Paired Chinese quote marks (supports nested pairs inside outer pair)
        if ch in QUOTE_PAIRS:
            close_ch = QUOTE_PAIRS[ch]
            start_line = line
            depth = 1
            j = i + 1
            inner_chars = []
            while j < n and depth > 0:
                cj = masked[j]
                if cj == "\n":
                    line += 1
                if cj == ch:
                    depth += 1
                    inner_chars.append(cj)
                elif cj == close_ch:
                    depth -= 1
                    if depth > 0:
                        inner_chars.append(cj)
                else:
                    inner_chars.append(cj)
                j += 1
            if depth == 0:
                quotes.append((start_line, ch, "".join(inner_chars)))
                i = j
            else:
                unclosed.append((start_line, ch))
                break
            continue

        i += 1

    return quotes, unclosed


def _find_all_segment_spans(src: str, segments: List[str]) -> List[Tuple[int, int]]:
    """Find candidate (start, end) spans in src where segments appear verbatim in order."""
    if not segments:
        return []
    first = segments[0]
    spans: List[Tuple[int, int]] = []
    pos = 0
    while True:
        idx = src.find(first, pos)
        if idx == -1:
            break
        cur = idx + len(first)
        ok = True
        for seg in segments[1:]:
            nxt = src.find(seg, cur)
            if nxt == -1:
                ok = False
                break
            cur = nxt + len(seg)
        if ok:
            spans.append((idx, cur))
        pos = idx + 1
    return spans


def _has_non_punct(s: str) -> bool:
    return any(ch not in PUNCT_AND_SPACE for ch in s)


def _check_span_truncation(src: str, start: int, end: int, last_seg: str) -> Tuple[bool, bool]:
    """Return (needs_leading_ellipsis, needs_trailing_ellipsis) for src[start:end]."""
    # Walk left until a clause boundary or start of source.
    l_idx = start - 1
    left_chars: List[str] = []
    while l_idx >= 0 and src[l_idx] not in CLAUSE_BOUNDARIES:
        left_chars.append(src[l_idx])
        l_idx -= 1
    needs_leading = _has_non_punct("".join(left_chars))

    # If the quoted span itself ends with a sentence-ending punctuation mark,
    # it already closes a complete clause unit.
    if last_seg and last_seg[-1] in SENTENCE_END_PUNCT:
        needs_trailing = False
    else:
        r_idx = end
        right_chars: List[str] = []
        while r_idx < len(src) and src[r_idx] not in CLAUSE_BOUNDARIES:
            right_chars.append(src[r_idx])
            r_idx += 1
        needs_trailing = _has_non_punct("".join(right_chars))

    return needs_leading, needs_trailing


def verify_single_quote(
    line: int, quote_char: str, inner: str, sources: Sequence[str]
) -> QuoteCheckItem:
    """Verify one extracted quote string against allowed verbatim sources."""
    if not inner.strip():
        return QuoteCheckItem(line, quote_char, inner, "EMPTY", "空引号")

    leading_ell = bool(re.match(r"^(?:……|\.\.\.|…)", inner))
    trailing_ell = bool(re.search(r"(?:……|\.\.\.|…)$", inner))
    has_ell = bool(re.search(r"……|\.\.\.|…", inner))

    raw_segments = [s for s in re.split(r"(?:……|\.\.\.|…+)", inner) if s]
    if not raw_segments:
        return QuoteCheckItem(line, quote_char, inner, "EMPTY", "引号内只有省略号")

    # Gather all verbatim matches across allowed sources.
    matched_candidates: List[Tuple[str, int, int]] = []
    for src in sources:
        for span in _find_all_segment_spans(src, raw_segments):
            matched_candidates.append((src, span[0], span[1]))

    if not matched_candidates:
        return QuoteCheckItem(
            line,
            quote_char,
            inner,
            "NOT_IN_SOURCE",
            "在用户提供的原文中逐字未找到（可能为非原文概念标签、自拟标题、抄错字或越界引用上下文）",
        )

    # Short-phrase exemption (applies when quote has no ellipsis):
    # < 8 non-punct characters AND contains none of ，。！？：；、
    if not has_ell:
        stripped_len = sum(1 for ch in inner if ch not in PUNCT_AND_SPACE)
        has_disallowed_punct = any(ch in SHORT_PHRASE_DISALLOWED_PUNCT for ch in inner)
        if stripped_len < 8 and not has_disallowed_punct:
            return QuoteCheckItem(line, quote_char, inner, "SHORT_PHRASE", "短词豁免")

    # Check if ANY matched occurrence satisfies completeness / ellipsis rules.
    best_failure: Optional[Tuple[str, str]] = None
    for src, start, end in matched_candidates:
        needs_lead, needs_trail = _check_span_truncation(src, start, end, raw_segments[-1])
        miss_lead = needs_lead and not leading_ell
        miss_trail = needs_trail and not trailing_ell
        if not miss_lead and not miss_trail:
            status = "EXCERPT_OK" if has_ell else "EXACT_UNIT"
            return QuoteCheckItem(line, quote_char, inner, status)

        if miss_lead and miss_trail:
            best_failure = ("MISSING_BOTH_ELLIPSIS", "节引首尾均被截断，两端均需标省略号……")
        elif miss_lead:
            best_failure = ("MISSING_LEADING_ELLIPSIS", "节引前端被截断，开头需标省略号……")
        else:
            best_failure = ("MISSING_TRAILING_ELLIPSIS", "节引后端被截断，结尾需标省略号……")

    assert best_failure is not None
    return QuoteCheckItem(line, quote_char, inner, best_failure[0], best_failure[1])


def replace_quotes_with_placeholder(text: str, placeholder: str = "") -> str:
    """Replace all top-level paired quotes with placeholder so narrator-only rules don't hit source text."""
    masked = strip_code_segments(text)
    out: List[str] = []
    i = 0
    n = len(masked)
    while i < n:
        ch = masked[i]
        if ch == '"':
            j = i + 1
            while j < n and masked[j] != '"':
                j += 1
            if placeholder:
                out.append(placeholder)
            i = j + 1 if j < n else n
            continue
        if ch in QUOTE_PAIRS:
            close_ch = QUOTE_PAIRS[ch]
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if masked[j] == ch:
                    depth += 1
                elif masked[j] == close_ch:
                    depth -= 1
                j += 1
            if placeholder:
                out.append(placeholder)
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_quotes_from_text(text: str) -> str:
    """Remove all top-level paired quotes from text so narrator-only rules don't hit Wu Cheng'en's text."""
    return replace_quotes_with_placeholder(text, placeholder="")


def find_equal_length_sentence_runs(narrator_text: str) -> List[str]:
    """Detect 3+ consecutive sentences of nearly identical length (within +/-2 hanzi, >=8 hanzi)."""
    sentences = [s.strip() for s in re.split(r"[。！？\n]+", narrator_text) if s.strip()]
    lengths = [count_hanzi(s) for s in sentences]
    warnings: List[str] = []
    i = 0
    while i <= len(sentences) - 3:
        window_lens = lengths[i : i + 3]
        if min(window_lens) >= 8 and (max(window_lens) - min(window_lens) <= 2):
            preview = " / ".join(f"{sentences[k][:12]}({lengths[k]}字)" for k in range(i, i + 3))
            warnings.append(f"连续三句长度雷同：{preview}")
            i += 3
        else:
            i += 1
    return warnings


def verify_draft(
    source_text: str,
    draft_text: str,
    genre: str = "spoken",
    min_hanzi: int = 1000,
    max_hanzi: int = 1200,
    user_msg_text: str = "",
    scan_scope: str = "full",
    ignored_sections: Sequence[str] = ("## 用户输入原文", "## 原始输入"),
) -> VerificationReport:
    sources = [source_text.replace("\r\n", "\n")]
    if user_msg_text.strip():
        sources.append(user_msg_text.replace("\r\n", "\n"))

    normalized_draft = draft_text.replace("\r\n", "\n")
    body_text = extract_body(normalized_draft, genre=genre)
    narrator_body = strip_quotes_from_text(body_text)

    body_hanzi = count_hanzi(body_text)
    narrator_hanzi = count_hanzi(narrator_body)

    hard_errors: List[str] = []
    warnings: List[str] = []

    # 1. Hanzi length gate
    length_ok = True
    if min_hanzi > 0 and body_hanzi < min_hanzi:
        length_ok = False
        hard_errors.append(
            f"正文本体汉字数不足：{body_hanzi} 字（要求 {min_hanzi}-{max_hanzi} 汉字，U+4E00-U+9FFF）"
        )
    if max_hanzi > 0 and body_hanzi > max_hanzi:
        length_ok = False
        hard_errors.append(
            f"正文本体汉字数超限：{body_hanzi} 字（要求 {min_hanzi}-{max_hanzi} 汉字，U+4E00-U+9FFF）"
        )

    # 2. Quote fidelity & scope lock scan
    quote_target = (
        body_text
        if scan_scope == "body"
        else remove_ignored_sections(normalized_draft, ignored_sections)
    )
    raw_quotes, unclosed = extract_quotes(quote_target)
    quote_items: List[QuoteCheckItem] = []
    for line_no, qch in unclosed:
        quote_items.append(
            QuoteCheckItem(line_no, qch, "", "UNCLOSED", f"第 {line_no} 行存在未闭合引号 {qch}")
        )
    for line_no, qch, inner in raw_quotes:
        quote_items.append(verify_single_quote(line_no, qch, inner, sources))

    quote_failures = [item for item in quote_items if not item.passed]
    for qf in quote_failures:
        hard_errors.append(
            f"引文核验失败 [第 {qf.line} 行][{qf.status}]：{qf.quote_char}{qf.text}{QUOTE_PAIRS.get(qf.quote_char, qf.quote_char)} —— {qf.detail}"
        )

    # 3. Hard style & forbidden checks on narrator prose (only for prose genres: spoken / article)
    contrast_hits: List[str] = []
    contrast_limit = max(1, narrator_hanzi // 1000)
    dan_hits: List[str] = []
    dan_limit = max(1, narrator_hanzi // 1000)
    dash_count = 0
    colon_count = 0
    exclam_count = 0

    if genre in ("spoken", "article"):
        for label, pattern in FORBIDDEN_PHRASE_PATTERNS:
            matches = re.findall(pattern, narrator_body)
            if matches:
                hard_errors.append(f"命中禁用短语 [{label}]（{len(matches)} 处）：{matches[0]}")

        # Negative contrast constructions: 0-1 per 1000 narrator hanzi (min cap 1 for short drafts)
        contrast_hits = [m.group(0) for m in NEGATIVE_CONTRAST_REGEX.finditer(narrator_body)]
        if len(contrast_hits) > contrast_limit:
            hard_errors.append(
                f"否定对照句式超限：{len(contrast_hits)} 处（上限 {contrast_limit} 处，按每千字 0-1 处、不含引文 {narrator_hanzi} 字计）—— {contrast_hits}"
            )

        # "但 / 但是": <= 1 per 1000 narrator hanzi (exclude 不但 / 但凡)
        dan_hits = re.findall(r"(?<!不)但是|(?<!不)但(?!凡)", narrator_body)
        if len(dan_hits) > dan_limit:
            hard_errors.append(
                f"“但/但是”超限：{len(dan_hits)} 处（上限 {dan_limit} 处，每千字最多 1 处）"
            )

        # Punctuation limits on narrator prose
        dash_count = len(re.findall(r"——", narrator_body))
        # Exclude markdown link schemes like http:// or file://
        colon_text = re.sub(r"[a-zA-Z]+://\S+", "", narrator_body)
        colon_count = colon_text.count("：") + colon_text.count(":")
        exclam_count = narrator_body.count("！") + narrator_body.count("!")

        if dash_count > 2:
            hard_errors.append(f"破折号（——）超限：{dash_count} 个（上限 2 个）")
        if colon_count > 3:
            hard_errors.append(f"冒号超限：{colon_count} 个（上限 3 个）")
        if exclam_count > 1:
            hard_errors.append(f"感叹号超限：{exclam_count} 个（上限 1 个，已扣除原著引文叹号）")

    # 4. Spoken script structural markers
    body_quote_count = 0
    if genre == "spoken":
        intro_idx = body_text.find(FIXED_INTRO_PREFIX)
        if intro_idx == -1:
            hard_errors.append(f"口播稿缺少固定开场白：{FIXED_INTRO_PREFIX}……")
        else:
            hook_part = body_text[:intro_idx].strip()
            if not hook_part:
                hard_errors.append("固定开场白前缺少钩子（顺序必须是：钩子 → 固定开场白）")
            else:
                # Collapse each quoted block into a single token so internal "！" inside a quote
                # doesn't inflate the hook sentence count.
                hook_norm = replace_quotes_with_placeholder(hook_part, placeholder="引文")
                hook_sents = [s for s in re.split(r"[。！？\n]+", hook_norm) if count_hanzi(s) > 0]
                if len(hook_sents) > 5:
                    hard_errors.append(f"钩子过长：{len(hook_sents)} 句（上限 5 句）")

        non_empty_lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
        if not non_empty_lines or non_empty_lines[-1] != FIXED_OUTRO_EXACT:
            hard_errors.append(f"口播正文末行必须一字不差以固定结束语收尾：{FIXED_OUTRO_EXACT}")

        # Warn if spoken body over-quotes (destroys spoken fluency and signals linear walkthrough)
        body_raw_quotes, _ = extract_quotes(body_text)
        body_quote_count = len(body_raw_quotes)
        if body_quote_count > 10:
            warnings.append(
                f"口播正文直接引号偏密（{body_quote_count} 处，建议短口播控制在 3-8 处核心短引，其余改用大白话复述）"
            )

    # 5. Soft warnings for Tier-1 & Tier-3 review (prose genres only)
    if genre in ("spoken", "article"):
        for label, pattern in AI_WARNING_PATTERNS:
            hits = re.findall(pattern, narrator_body)
            if hits:
                warnings.append(f"{label}提示（{len(hits)} 处）：{', '.join(dict.fromkeys(hits))}")

        if re.search(r"第一[，、：:].*第二[，、：:].*第三", narrator_body, re.S) or (
            "首先" in narrator_body and "其次" in narrator_body
        ):
            warnings.append("检测到结构化枚举（第一/第二/第三 或 首先/其次），口播稿应改为自然递进")

        # Detect repetitive substitute conjunctions / emphasis words / identical boundary templates
        que_count = narrator_body.count("却")
        if que_count >= 4:
            warnings.append(f"替用转折词“却”偏密（{que_count} 处，建议压到 3 处以内，改用零连词短句断开）")

        zhenzheng_count = narrator_body.count("真正")
        if zhenzheng_count >= 3:
            warnings.append(f"强调词“真正”复读偏密（{zhenzheng_count} 处，建议压到 2 处以内）")

        pullback_hits = re.findall(r"回到(?:字面|这几行字|原文)[^。！？\n]{0,6}(?:看|里|就能)", narrator_body)
        if len(pullback_hits) >= 2:
            warnings.append(f"边界回拉句式同构重复（{len(pullback_hits)} 处）：{', '.join(pullback_hits)}")

        warnings.extend(find_equal_length_sentence_runs(narrator_body))

    metrics = {
        "body_hanzi": body_hanzi,
        "narrator_hanzi": narrator_hanzi,
        "quote_total": len(quote_items),
        "quote_failed": len(quote_failures),
        "negative_contrast": len(contrast_hits),
        "negative_contrast_limit": contrast_limit,
        "dan_count": len(dan_hits),
        "dan_limit": dan_limit,
        "dash_count": dash_count,
        "colon_count": colon_count,
        "exclam_count": exclam_count,
    }

    return VerificationReport(
        passed=(len(hard_errors) == 0),
        genre=genre,
        body_hanzi=body_hanzi,
        narrator_hanzi=narrator_hanzi,
        min_hanzi=min_hanzi,
        max_hanzi=max_hanzi,
        length_ok=length_ok,
        quote_total=len(quote_items),
        quote_failures=quote_failures,
        quote_items=quote_items,
        hard_errors=hard_errors,
        warnings=warnings,
        metrics=metrics,
    )


def format_report_text(report: VerificationReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [
        f"=== 机械校验结果：{status} (genre={report.genre}) ===",
        f"正文本体汉字数：{report.body_hanzi}（不含引文：{report.narrator_hanzi}；目标：{report.min_hanzi}-{report.max_hanzi}）",
        f"引文扫描：{report.quote_total} 处引号，失败 {len(report.quote_failures)} 处",
        (
            f"硬指标计数：否定对照 {report.metrics['negative_contrast']}/{report.metrics['negative_contrast_limit']} | "
            f"但/但是 {report.metrics['dan_count']}/{report.metrics['dan_limit']} | "
            f"破折号 {report.metrics['dash_count']}/2 | "
            f"冒号 {report.metrics['colon_count']}/3 | "
            f"感叹号 {report.metrics['exclam_count']}/1"
        ),
    ]
    if report.hard_errors:
        lines.append("\n[硬项未通过]")
        for idx, err in enumerate(report.hard_errors, 1):
            lines.append(f"  {idx}. {err}")
    if report.warnings:
        lines.append("\n[一审/三审软提醒]")
        for idx, warn in enumerate(report.warnings, 1):
            lines.append(f"  {idx}. {warn}")
    if not report.hard_errors and not report.warnings:
        lines.append("全部硬项与软提醒均零异常。")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic verifier for xiyouji-interpret drafts."
    )
    src_group = parser.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--source", type=Path, help="Path to user-provided source passage")
    src_group.add_argument("--source-text", type=str, help="Inline user-provided source passage")

    parser.add_argument("--draft", type=Path, required=True, help="Path to deliverable/draft markdown")
    parser.add_argument("--user-msg", type=Path, help="Optional file containing verbatim user message")
    parser.add_argument(
        "--genre",
        choices=("spoken", "article", "none"),
        default="spoken",
        help="Target genre (default: spoken)",
    )
    parser.add_argument("--min-hanzi", type=int, default=1000, help="Min body hanzi (0 to disable)")
    parser.add_argument("--max-hanzi", type=int, default=1200, help="Max body hanzi (0 to disable)")
    parser.add_argument(
        "--scan-scope",
        choices=("full", "body"),
        default="full",
        help="Quote scan scope: full deliverable (default) or body only",
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if warnings exist")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args(argv)

    source_text = (
        args.source.read_text(encoding="utf-8") if args.source else args.source_text
    )
    draft_text = args.draft.read_text(encoding="utf-8")
    user_msg_text = args.user_msg.read_text(encoding="utf-8") if args.user_msg else ""

    report = verify_draft(
        source_text=source_text,
        draft_text=draft_text,
        genre=args.genre,
        min_hanzi=args.min_hanzi,
        max_hanzi=args.max_hanzi,
        user_msg_text=user_msg_text,
        scan_scope=args.scan_scope,
    )

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(format_report_text(report))

    if not report.passed:
        return 1
    if args.strict and report.warnings:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
