"""텍스트 추출 (설계서 4.8): HWPX 문서를 검토·요약용 마크다운으로 변환한다.

변환 규칙
- 문단: 텍스트 그대로(□ ○ - · 등 개조식 기호 유지). 앞쪽 공백 들여쓰기는 마크다운 코드 블록으로
  오인되지 않도록 제거하고, 문단 안 줄바꿈은 줄 끝 두 칸 공백으로 유지한다.
- 자동 번호·글머리표(문단모양의 번호/개요/글머리표)는 번호를 계산해 앞에 붙인다(1. 가. 1) ① •).
- 표: 병합·중첩이 없으면 마크다운 표, 있으면 HTML 표(rowspan/colspan 유지). --tables md|html 로 고정 가능.
  칸이 하나뿐인 표(제목 상자·안내 상자)는 인용문(>)으로 쓴다.
- 기호 글꼴(Wingdings 등, 유니코드 사용자 정의 영역)로 입력된 글머리 기호는 • 로 바꾼다.
- 그림: [그림: image3.png] 표시. 글상자(사각형 등)의 글은 인용문으로 쓴다.
- 메모: 메모가 달린 글 뒤에 〔메모n〕 표시, 문서 끝에 메모 목록(작성자·내용).
- 각주·미주: [^n] 표시와 문서 끝 목록.
- 입력 전 누름틀: 안내문 대신 {{누름틀 이름}} 으로 표시.
- 머리말·꼬리말은 기본 제외(--headers 로 포함).
"""

from __future__ import annotations

import html
import re

from lxml import etree

from . import q
from .locate import T_P, T_RUN, T_T, T_TBL, cells_of, text_of_t
from .package import HwpxPackage

T_CTRL, T_SUB = q("hp", "ctrl"), q("hp", "subList")
T_FB, T_FE = q("hp", "fieldBegin"), q("hp", "fieldEnd")
T_PIC, T_DT = q("hp", "pic"), q("hp", "drawText")
T_EQ = q("hp", "equation")
NOTE_TAGS = {q("hp", "footNote"): "각주", q("hp", "endNote"): "미주"}
HF_TAGS = {q("hp", "header"): "머리말", q("hp", "footer"): "꼬리말"}

_HANGUL = "가나다라마바사아자차카타파하"
_CIRC_HANGUL = "㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷㉸㉹㉺㉻"


def _fmt_num(n: int, fmt: str) -> str:
    if fmt in ("HANGUL_SYLLABLE", "HANGUL_JAMO"):
        return _HANGUL[(n - 1) % len(_HANGUL)]
    if fmt == "CIRCLED_DIGIT":
        return chr(0x2460 + n - 1) if 1 <= n <= 20 else f"({n})"
    if fmt == "CIRCLED_HANGUL_SYLLABLE":
        return _CIRC_HANGUL[(n - 1) % len(_CIRC_HANGUL)]
    if fmt == "LATIN_SMALL":
        return chr(ord("a") + (n - 1) % 26)
    if fmt == "LATIN_CAPITAL":
        return chr(ord("A") + (n - 1) % 26)
    if fmt in ("ROMAN_SMALL", "ROMAN_CAPITAL"):
        vals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
        out, k = "", n
        for v, s in vals:
            while k >= v:
                out, k = out + s, k - v
        return out.upper() if fmt == "ROMAN_CAPITAL" else out
    return str(n)


class _Numbering:
    """문단모양의 자동 번호(NUMBER·OUTLINE)·글머리표(BULLET) 계산."""

    def __init__(self, pkg: HwpxPackage):
        name = next((n for n in pkg.names() if n.lower().endswith("header.xml")), None)
        self.para, self.nums, self.bullets = {}, {}, {}
        self.counters: dict[str, list[int]] = {}
        if not name:
            return
        root = pkg.xml(name).getroot()
        for pp in root.iter(q("hh", "paraPr")):
            hd = next(pp.iter(q("hh", "heading")), None)
            if hd is not None and hd.get("type", "NONE") != "NONE":
                self.para[pp.get("id")] = (hd.get("type"), hd.get("idRef"), int(hd.get("level", 0)))
        for nb in root.iter(q("hh", "numbering")):
            self.nums[nb.get("id")] = {int(h.get("level")): (h.text or "", h.get("numFormat", "DIGIT"))
                                       for h in nb.iter(q("hh", "paraHead"))}
        for b in root.iter(q("hh", "bullet")):
            ch = b.get("char", "•")
            self.bullets[b.get("id")] = "•" if (not ch or 0xE000 <= ord(ch[0]) <= 0xF8FF) else ch
        self.outline_id = None
        for sec in pkg.sections():
            sp = next(sec.iter(q("hp", "secPr")), None)
            if sp is not None and sp.get("outlineShapeIDRef"):
                self.outline_id = sp.get("outlineShapeIDRef")
                break

    def prefix(self, p: etree._Element) -> str:
        info = self.para.get(p.get("paraPrIDRef"))
        if not info:
            return ""
        kind, ref, level = info
        if kind == "BULLET":
            return self.bullets.get(ref, "•") + " "
        nid = ref if kind == "NUMBER" else (self.outline_id or ref or "1")
        heads = self.nums.get(nid)
        if not heads:
            return ""
        cnt = self.counters.setdefault(nid, [0] * 11)
        lv = level + 1
        cnt[lv] += 1
        for k in range(lv + 1, 11):
            cnt[k] = 0
        pat, _ = heads.get(lv, ("", "DIGIT"))
        if not pat:
            return ""
        out = re.sub(r"\^(\d+)", lambda m: _fmt_num(max(cnt[int(m.group(1))], 1),
                                                     heads.get(int(m.group(1)), ("", "DIGIT"))[1]), pat)
        return out + " "


class Extractor:
    def __init__(self, pkg: HwpxPackage, tables: str = "auto", headers: bool = False):
        self.pkg, self.tables, self.headers = pkg, tables, headers
        self.num = _Numbering(pkg)
        self.memos: list[tuple[int, str, str]] = []
        self.notes: list[tuple[int, str, str]] = []
        self.hf: list[tuple[str, str]] = []
        self.images = {it.get("id"): it.get("href", "") for it in pkg.manifest_items()}
        self.stats = {"문단": 0, "표": 0, "그림": 0}

    # ------------------------------------------------------------ 문단 → 블록
    def blocks(self, p: etree._Element) -> list[tuple]:
        """('p', 텍스트) | ('table', tbl) | ('box', [블록]) | ('img', 이름) | ('hr',)"""
        out, buf = [], []
        open_memo: dict[str, int] = {}
        suppress: str | None = None

        def flush():
            if buf:
                out.append(("p", "".join(buf)))
                buf.clear()

        if p.get("pageBreak") == "1":
            out.append(("hr",))
        for run in p.findall(T_RUN):
            for ch in run:
                tag = ch.tag
                if tag == T_T:
                    if suppress is None:
                        buf.append(text_of_t(ch))
                elif tag == T_CTRL:
                    for c in ch:
                        if c.tag == T_FB:
                            ftype = c.get("type")
                            if ftype == "MEMO":
                                n = len(self.memos) + 1
                                author = next((sp.text for sp in c.iter(q("hp", "stringParam"))
                                               if sp.get("name") == "Author"), "") or ""
                                body = self._sub_text(c.find(T_SUB))
                                self.memos.append((n, author, body))
                                open_memo[c.get("id")] = n
                            elif ftype == "CLICK_HERE" and c.get("dirty") != "1":
                                suppress = c.get("id")
                                buf.append("{{" + (c.get("name") or "누름틀") + "}}")
                        elif c.tag == T_FE:
                            bid = c.get("beginIDRef")
                            if bid in open_memo:
                                buf.append(f"〔메모{open_memo.pop(bid)}〕")
                            if bid == suppress:
                                suppress = None
                        elif c.tag in NOTE_TAGS:
                            n = len(self.notes) + 1
                            self.notes.append((n, NOTE_TAGS[c.tag], self._sub_text(c.find(T_SUB))))
                            buf.append(f"[^{n}]")
                        elif c.tag in HF_TAGS and self.headers:
                            self.hf.append((HF_TAGS[c.tag], self._sub_text(c.find(T_SUB))))
                elif tag == T_TBL:
                    flush()
                    out.append(("table", ch))
                elif tag == T_PIC:
                    flush()
                    out.append(("img", self._img_name(ch)))
                elif tag == T_EQ:
                    sc = ch.find(q("hp", "script"))
                    buf.append(f"[수식: {(sc.text or '').strip() if sc is not None else ''}]")
                else:
                    dts = list(ch.iter(T_DT))
                    if dts:
                        flush()
                        inner = []
                        for dt in dts:
                            for sp in dt.findall(T_SUB):
                                for pp in sp.findall(T_P):
                                    inner += self.blocks(pp)
                        out.append(("box", inner))
                    pics = [x for x in ch.iter(T_PIC)]
                    for x in pics:
                        flush()
                        out.append(("img", self._img_name(x)))
        flush()
        pre = self.num.prefix(p)
        if pre:
            for i, b in enumerate(out):
                if b[0] == "p":
                    out[i] = ("p", pre + b[1].lstrip())
                    break
            else:
                if not out:
                    out.append(("p", pre.strip()))
        if not any(b[0] == "p" for b in out) and not out:
            out.append(("p", ""))
        return out

    def _img_name(self, pic) -> str:
        self.stats["그림"] += 1
        img = next(pic.iter(q("hc", "img")), None)
        ref = img.get("binaryItemIDRef") if img is not None else None
        href = self.images.get(ref, ref or "")
        return href.split("/")[-1] if href else "그림"

    def _sub_text(self, sub) -> str:
        if sub is None:
            return ""
        lines = []
        for pp in sub.findall(T_P):
            for b in self.blocks(pp):
                if b[0] == "p":
                    lines.append(b[1].strip())
                elif b[0] == "table":
                    lines.append(self._cell_inline_table(b[1]))
        return " / ".join(x for x in lines if x)

    # ------------------------------------------------------------ 표
    def _cell_content(self, tc, mode: str) -> str:
        parts = []
        sub = tc.find(T_SUB)
        for pp in (sub.findall(T_P) if sub is not None else []):
            for b in self.blocks(pp):
                if b[0] == "p":
                    t = b[1].strip()
                    t = html.escape(t, quote=False) if mode == "html" else t.replace("|", "\\|")
                    parts.append(t.replace("\n", "<br>"))
                elif b[0] == "table":
                    parts.append(self._table_html(b[1]) if mode == "html" else self._cell_inline_table(b[1]))
                elif b[0] == "img":
                    parts.append(f"[그림: {b[1]}]")
                elif b[0] == "box":
                    parts.append(" ".join(x[1].strip() for x in b[1] if x[0] == "p"))
        while parts and not parts[-1]:
            parts.pop()
        return "<br>".join(parts)

    def _cell_inline_table(self, tbl) -> str:
        rows = {}
        for c in cells_of(tbl):
            rows.setdefault(c.row, []).append((c.col, self._cell_content(c.el, "md")))
        return " ; ".join(" , ".join(t for _, t in sorted(v)) for _, v in sorted(rows.items()))

    def _table_html(self, tbl) -> str:
        rows = {}
        for c in cells_of(tbl):
            rows.setdefault(c.row, []).append(c)
        out = ["<table>"]
        for r in sorted(rows):
            out.append("<tr>")
            for c in sorted(rows[r], key=lambda x: x.col):
                tag = "th" if c.el.get("header") == "1" else "td"
                attrs = (f' rowspan="{c.rowspan}"' if c.rowspan > 1 else "") + (f' colspan="{c.colspan}"' if c.colspan > 1 else "")
                out.append(f"<{tag}{attrs}>{self._cell_content(c.el, 'html')}</{tag}>")
            out.append("</tr>")
        out.append("</table>")
        return "".join(out)

    def table(self, tbl) -> str:
        self.stats["표"] += 1
        cs = cells_of(tbl)
        nrows, ncols = int(tbl.get("rowCnt", 0)), int(tbl.get("colCnt", 0))
        if len(cs) == 1:  # 제목·안내 상자
            body = self._cell_content(cs[0].el, "md").replace("<br>", "\n")
            return "\n".join("> " + ln if ln.strip() else ">" for ln in body.split("\n"))
        merged = any(c.rowspan > 1 or c.colspan > 1 for c in cs)
        nested = any(next(c.el.iter(T_TBL), None) is not None for c in cs)
        mode = self.tables if self.tables in ("md", "html") else ("html" if merged or nested else "md")
        if mode == "html":
            return self._table_html(tbl)
        grid = [[""] * ncols for _ in range(nrows)]
        for c in cs:
            if c.row < nrows and c.col < ncols:
                grid[c.row][c.col] = self._cell_content(c.el, "md")
        lines = ["| " + " | ".join(grid[0]) + " |", "|" + " --- |" * ncols]
        lines += ["| " + " | ".join(r) + " |" for r in grid[1:]]
        return "\n".join(lines)

    # ------------------------------------------------------------ 전체
    def render_blocks(self, bs: list[tuple]) -> list[str]:
        out = []
        for b in bs:
            if b[0] == "p":
                self.stats["문단"] += 1
                t = re.sub(r"[\ue001-\uf8ff]", "•", b[1]).rstrip()  # 기호 글꼴(사용자 정의 영역) 글머리 → •
                lines = [re.sub(r"^[ \t　]+", "", ln).rstrip() for ln in t.split("\n")]
                lines = [("\\" + ln) if re.match(r"^(#|>|\+ |=+$)", ln) else ln for ln in lines]
                out.append("  \n".join(lines))
            elif b[0] == "table":
                out.append("")
                out.append(self.table(b[1]))
                out.append("")
            elif b[0] == "img":
                out.append(f"[그림: {b[1]}]")
            elif b[0] == "box":
                inner = [ln for ln in self.render_blocks(b[1]) if ln is not None]
                out.append("\n".join("> " + x if x else ">" for x in "\n".join(inner).split("\n")))
            elif b[0] == "hr":
                out.append("\n---\n")
        return out

    def run(self) -> str:
        parts = []
        for si, sec in enumerate(self.pkg.sections()):
            if si:
                parts.append("\n---\n")
            for p in sec.findall(T_P):
                parts += self.render_blocks(self.blocks(p))
        md = "\n".join(parts)
        md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
        tail = []
        if self.memos:
            tail.append("\n## 메모\n")
            tail += [f"- 〔메모{n}〕 ({a}) {t}" for n, a, t in self.memos]
        if self.notes:
            tail.append("")
            tail += [f"[^{n}]: ({k}) {t}" for n, k, t in self.notes]
        if self.hf:
            tail.append("\n## 머리말·꼬리말\n")
            tail += [f"- {k}: {t}" for k, t in self.hf]
        return md + ("\n".join(tail) + "\n" if tail else "")


def extract(path: str, tables: str = "auto", headers: bool = False) -> tuple[str, dict]:
    ex = Extractor(HwpxPackage.open(path), tables, headers)
    md = ex.run()
    st = dict(ex.stats, 메모=len(ex.memos), 각주=len(ex.notes))
    return md, st
