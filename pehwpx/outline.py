"""개조식 본문 작성 (설계서 4.4): 들여쓰기 목록을 공공 보고서·공문 위계 기호와 내어쓰기로 바꿔 양식에 넣는다.

입력(본문 파일, UTF-8 텍스트)
    - 1수준 항목                 '- ' 또는 '* ' 로 시작, 앞 공백 2칸(또는 탭 1개)마다 한 수준 아래
      - 2수준 항목
        - 3수준 항목
    ※ 참고 문구                   '※ ' 로 시작하면 그 위치 수준의 참고(기호 ※ 그대로)
    본문 문단                     기호 없는 줄은 바로 위 항목의 내용 위치에 맞춘 이어지는 문단
    빈 줄은 무시한다.

위계 기호 (style)
    report : □ → ○ → - → · → (5수준 이후 ·)
    gonmun : 1. → 가. → 1) → 가) → (1) → (가) → ① → ㉮  (「행정업무의 운영 및 혁신에 관한 규정 시행규칙」 항목 순서)

배치 규칙
    - 하위 항목은 상위 항목 기호 위치에서 indent_em(기본 1글자 = 2타) 오른쪽에서 시작한다.
    - 모든 항목에 내어쓰기를 적용해, 줄이 넘어가면 둘째 줄이 첫 줄 내용(기호 다음 글자) 위치에 맞도록 한다.
    - 글자모양·줄 간격·문단 위아래 간격은 기준 문단(삽입 위치의 문단)을 따르고, 필요한 문단모양은 header 끝에 추가한다.
    - gonmun 은 end=True 이면 마지막 문단 끝에 2타 띄우고 '끝.' 을 붙인다.
"""

from __future__ import annotations

import copy
import re

from lxml import etree

from . import q
from .locate import T_P, T_RUN, T_T, norm, paragraph_text

T_LSA = q("hp", "linesegarray")

REPORT = ["□", "○", "-", "·"]
FW_COUNT = 2  # 기호 뒤 고정폭 빈칸 수: 고정폭 빈칸 1개 ≈ 0.25글자, 2개 ≈ 반 글자(1타)
_HANGUL = "가나다라마바사아자차카타파하"
_CIRC = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
_CIRC_H = "㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷㉸㉹㉺㉻"


class OutlineError(ValueError):
    pass


def gonmun_mark(level: int, n: int) -> str:
    h = _HANGUL[(n - 1) % len(_HANGUL)]
    return [f"{n}.", f"{h}.", f"{n})", f"{h})", f"({n})", f"({h})",
            _CIRC[(n - 1) % len(_CIRC)], _CIRC_H[(n - 1) % len(_CIRC_H)]][min(level, 7)]


def parse(text: str) -> list[dict]:
    """→ [{'kind': 'item'|'note'|'body', 'level': n(0부터), 'text': ...}]"""
    out, last_level = [], -1
    for raw in text.splitlines():
        if not raw.strip():
            continue
        line = raw.replace("\t", "  ")
        lead = len(line) - len(line.lstrip(" "))
        body = line.strip()
        m = re.match(r"^[-*]\s+(.*)$", body)
        if m:
            lv = lead // 2
            if lv > last_level + 1:
                lv = last_level + 1  # 수준을 건너뛰면 한 단계 아래로 맞춤
            out.append({"kind": "item", "level": lv, "text": m.group(1).strip()})
            last_level = lv
        elif body.startswith("※"):
            lv = max(0, min(lead // 2, last_level + 1))
            out.append({"kind": "note", "level": lv, "text": body})
        else:
            out.append({"kind": "body", "level": max(last_level, 0), "text": body})
    return out


def _w(s: str, height: int, ratio: int) -> int:
    """기호+빈칸의 대략 폭(HWPUNIT): 전각 1em, 반각 0.55em, 마침표·괄호 0.35em,
    끝의 빈칸은 고정폭 빈칸(0.25em × FW_COUNT). 정확한 값은 probe 실측 사용."""
    body = s.rstrip(" ")
    em = sum(1.0 if ord(ch) > 0x2000 else (0.35 if ch in ".()" else 0.55) for ch in body)
    em += 0.25 * FW_COUNT
    return int(em * height * ratio / 100)


class Writer:
    def __init__(self, pkg, style: str = "report", indent_em: float = 1.0, sym_scale: float = 1.0,
                 metrics: dict | None = None):
        if style not in ("report", "gonmun"):
            raise OutlineError("style 은 report 또는 gonmun")
        self.pkg, self.style, self.indent_em, self.sym_scale = pkg, style, indent_em, sym_scale
        self.metrics = metrics or {}  # {"기호+공백": 폭(HWPUNIT), "_em": 한 글자 폭} — 한글 PDF 실측값(probe)
        self.hname = next(n for n in pkg.names() if n.lower().endswith("header.xml"))
        root = pkg.xml(self.hname).getroot()
        self.pps = {e.get("id"): e for e in root.iter(q("hh", "paraPr"))}
        self.cps = {e.get("id"): e for e in root.iter(q("hh", "charPr"))}

    # ------------------------------------------------------------ 문단모양
    def _parapr(self, base_id: str, left: int, intent: int) -> str:
        src = self.pps[base_id]
        new = copy.deepcopy(src)
        # 한글 문단 여백: left = 첫 줄 시작, intent < 0 이면 둘째 줄부터 |intent| 만큼 더 들어감(내어쓰기).
        # hp:switch 의 hp:case(HwpUnitChar) 값이 기준이고, hp:default(구버전 호환)는 그 2배로 저장된다(한글 저장 문서 실측).
        for mg in new.iter(q("hh", "margin")):
            scale = 2 if mg.getparent() is not None and etree.QName(mg.getparent()).localname == "default" else 1
            for tag, val in (("left", left), ("intent", intent)):
                el = mg.find(q("hc", tag))
                if el is not None:
                    el.set("value", str(val * scale))
        for hd in new.iter(q("hh", "heading")):  # 자동 번호·글머리표는 끈다(기호는 글자로 넣음)
            hd.set("type", "NONE")
            hd.set("idRef", "0")
            hd.set("level", "0")

        def key(el):
            c = copy.deepcopy(el)
            c.attrib.pop("id", None)
            return etree.tostring(c)

        want = key(new)
        for oid, el in self.pps.items():
            if key(el) == want:
                return oid
        nid = str(max(int(i) for i in self.pps) + 1)
        new.set("id", nid)
        parent = src.getparent()
        parent.append(new)
        if parent.get("itemCnt"):
            parent.set("itemCnt", str(len(parent.findall(q("hh", "paraPr")))))
        self.pps[nid] = new
        self.pkg.touch(self.hname)
        return nid

    def _base_left(self, base_id: str) -> int:
        """기준 문단의 첫 줄 시작 위치. 한글은 왼쪽 여백(left)이 첫 줄 시작이고, 내어쓰기(intent<0)는 둘째 줄에만 적용된다."""
        mg = next(self.pps[base_id].iter(q("hh", "margin")), None)
        if mg is None:
            return 0
        el, it = mg.find(q("hc", "left")), mg.find(q("hc", "intent"))
        left = int(el.get("value")) if el is not None else 0
        intent = int(it.get("value")) if it is not None else 0
        return max(0, left + max(intent, 0))  # 들여쓰기(양수)면 첫 줄이 그만큼 더 들어감

    # ------------------------------------------------------------ 문단 만들기
    def build(self, items: list[dict], template: etree._Element, end: bool = False) -> list[etree._Element]:
        base_pp = template.get("paraPrIDRef")
        run0 = next((r for r in template.findall(T_RUN) if r.findall(T_T)), None)
        if run0 is None:
            run0 = template.find(T_RUN)
        cp = run0.get("charPrIDRef") if run0 is not None else "0"
        cpe = self.cps.get(cp)
        height = int(cpe.get("height", 1000)) if cpe is not None else 1000
        ratio_el = cpe.find(q("hh", "ratio")) if cpe is not None else None
        ratio = int(ratio_el.get("hangul", 100)) if ratio_el is not None else 100
        base_left = self._base_left(base_pp)
        em = int(self.metrics.get("_em", height * ratio / 100))
        step = int(self.indent_em * em)
        counters = [0] * 10
        starts: dict[int, int] = {}   # 수준별 기호 시작 위치
        text_at: dict[int, int] = {}  # 수준별 내용 시작 위치
        out = []
        for it in items:
            lv = it["level"]
            if it["kind"] == "item":
                counters[lv] += 1
                for k in range(lv + 1, 10):
                    counters[k] = 0
                mark = (REPORT[min(lv, 3)] if self.style == "report" else gonmun_mark(lv, counters[lv]))
                start = base_left if lv == 0 else starts.get(lv - 1, base_left) + step
                sym = mark + " "
                hang = self._hang(sym, height, ratio)
                starts[lv], text_at[lv] = start, start + hang
                for k in [k for k in starts if k > lv]:
                    starts.pop(k)
                    text_at.pop(k, None)
                pid = self._parapr(base_pp, start, -hang)
                text = sym + it["text"]
            elif it["kind"] == "note":
                start = base_left if lv == 0 else starts.get(lv - 1, base_left) + step
                sym = "※ "
                hang = self._hang(sym, height, ratio)
                pid = self._parapr(base_pp, start, -hang)
                text = it["text"] if it["text"].startswith("※ ") else "※ " + it["text"][1:].lstrip()
            else:  # 이어지는 본문: 바로 위 항목의 내용 위치
                left = text_at.get(lv, base_left)
                pid = self._parapr(base_pp, left, 0)
                text = it["text"]
            out.append(self._para(template, pid, cp, text, sym=it["kind"] != "body"))
        if end and out:
            last = out[-1].find(T_RUN).find(T_T)
            if len(last):
                last[-1].tail = (last[-1].tail or "").rstrip() + "  끝."
            else:
                last.text = (last.text or "").rstrip() + "  끝."
        return out

    def _hang(self, sym: str, height: int, ratio: int) -> int:
        if sym in self.metrics:
            return int(self.metrics[sym])
        key = re.sub(r"\d+", "1", sym)  # 번호 자릿수 차이는 숫자 폭 비율로 보정
        if key in self.metrics:
            extra = len(sym) - len(key)
            return int(self.metrics[key] + extra * self.metrics.get("_digit", height * ratio / 200))
        return int(_w(sym, height, ratio) * self.sym_scale)

    @staticmethod
    def _para(template, pid: str, cp: str, text: str, sym: bool = False) -> etree._Element:
        p = etree.Element(T_P, dict(template.attrib))
        p.set("paraPrIDRef", pid)
        for k in ("pageBreak", "columnBreak"):
            if p.get(k):
                p.set(k, "0")
        run = etree.SubElement(p, T_RUN)
        run.set("charPrIDRef", cp)
        t = etree.SubElement(run, T_T)
        m = re.match(r"^(\S+) (.*)$", text) if sym else None
        if m:  # 기호 뒤 빈칸은 고정폭 빈칸: 양쪽 정렬에서 늘어나지 않아 내어쓰기 위치가 맞는다
            t.text = m.group(1)
            fw = None
            for _ in range(FW_COUNT):
                fw = etree.SubElement(t, q("hp", "fwSpace"))
            fw.tail = m.group(2)
        else:
            t.text = text
        return p


# ---------------------------------------------------------------- 삽입 위치
def find_paragraph(secs, phrase: str, nth: int = 1):
    want = norm(phrase)
    hits = [p for sec in secs for p in sec.iter(T_P) if want and want in norm(paragraph_text(p))]
    if len(hits) < nth:
        raise OutlineError(f"'{phrase}' 가 든 문단을 찾지 못함 (발견 {len(hits)}건)")
    return hits[nth - 1]


def is_empty(p) -> bool:
    if paragraph_text(p).strip():
        return False
    return not any(ch.tag not in (T_T, q("hp", "linesegarray")) for r in p.findall(T_RUN) for ch in r) \
        and p.find(q("hp", "ctrl")) is None


def has_object(p) -> bool:
    return any(ch.tag != T_T for r in p.findall(T_RUN) for ch in r)


def _sig(p) -> str:
    return etree.tostring(p)


def apply(pkg, loc, items: list[dict], style: str, *, at: str | None = None, after: str | None = None,
          replace: str | None = None, to: str | None = None, nth: int = 1, consume_empty: bool = False,
          like: str | None = None, end: bool = False, indent_em: float = 1.0, metrics: dict | None = None) -> dict:
    """본문을 넣고 {'allowed': set, 'inserted': n, 'removed': n, 'where': str} 를 돌려준다."""
    w = Writer(pkg, style, indent_em, metrics=metrics)
    secs = loc.secs
    if at:
        tgt = loc.resolve(at)
        if tgt.kind != "cell":
            raise OutlineError("--at 은 표 칸 경로(s0/tbl[k]/r[i]/c[j])")
        sub = tgt.el.find(q("hp", "subList"))
        ps = sub.findall(T_P)
        if any(has_object(p) for p in ps):
            raise OutlineError(f"{at}: 칸 안에 표·그림 등 개체가 있어 칸 전체 교체 불가 (--after/--replace 사용)")
        parent, first, removed = sub, list(sub).index(ps[0]), ps
        template = ps[0]
    elif replace:
        a = find_paragraph(secs, replace, nth)
        b = find_paragraph(secs, to, 1) if to else a
        parent = a.getparent()
        if b.getparent() is not parent:
            raise OutlineError("--replace 와 --to 문단이 같은 칸(또는 본문)에 있지 않음")
        sibs = parent.findall(T_P)
        i, j = sibs.index(a), sibs.index(b)
        if j < i:
            raise OutlineError("--to 문단이 --replace 문단보다 앞에 있음")
        removed = sibs[i:j + 1]
        if any(has_object(p) for p in removed):
            raise OutlineError("바꿀 범위에 표·그림 등 개체가 든 문단이 있음")
        first, template = list(parent).index(a), a
    elif after:
        a = find_paragraph(secs, after, nth)
        parent = a.getparent()
        sibs = parent.findall(T_P)
        i = sibs.index(a)
        first = list(parent).index(a) + 1
        nxt = sibs[i + 1] if i + 1 < len(sibs) else None
        template = nxt if (nxt is not None and not has_object(nxt)) else a
        removed = []
        if consume_empty:
            for p in sibs[i + 1:]:
                if is_empty(p) and len(removed) < len(items):
                    removed.append(p)
                else:
                    break
    else:
        raise OutlineError("--at, --after, --replace 중 하나가 필요함")
    if like:
        template = find_paragraph(secs, like, 1)
    before = [_sig(p) for p in parent]
    new = w.build(items, template, end=end and style == "gonmun")
    for p in removed:
        parent.remove(p)
    for k, p in enumerate(new):
        parent.insert(first + k, p)
    # 바뀌지 않아야 할 앞·뒤 형제 확인
    after_sig = [_sig(p) for p in parent]
    n_head = first
    n_tail = len(before) - first - len(removed)
    if before[:n_head] != after_sig[:n_head] or (n_tail and before[-n_tail:] != after_sig[-n_tail:]):
        raise OutlineError("삽입 범위 밖 문단이 바뀜(내부 오류)")
    # 허용 범위
    allowed = set()
    tc = next((x for x in [parent, *parent.iterancestors()] if x.tag == q("hp", "tc")), None)
    if tc is not None:
        allowed.add(loc.where(tc))
    else:
        si = secs.index(parent) if parent in secs else 0
        allowed.add(f"s{si}#section")
        tops = parent.findall(T_P)
        for k in range(tops.index(new[0]) if new else first, len(tops)):
            allowed.add(f"s{si}/p[{k}]")
    si = next(i for i, s in enumerate(secs) if s is parent or s in parent.iterancestors())
    pkg.touch(pkg.section_names()[si])
    return {"allowed": allowed, "inserted": len(new), "removed": len(removed),
            "where": loc.where(new[0]) if new else "", "template": paragraph_text(template)[:30]}


# ---------------------------------------------------------------- 기호 폭 실측 (probe)
PROBE_SYMS = ["□ ", "○ ", "- ", "· ", "※ ", "1. ", "가. ", "1) ", "가) ", "(1) ", "(가) ", "① ", "㉮ "]
PROBE_TAIL = "한한"  # ㅁ 은 글꼴에 따라 첫가끝 자모로 추출되어 음절 글자 사용


def make_probe(pkg, loc, like: str, nth: int = 1) -> int:
    """기준 문단(like)과 같은 글자모양으로 기호 폭 측정용 문단을 구역 0 맨 앞에 넣는다(측정 전용 사본)."""
    tpl = find_paragraph(loc.secs, like, nth)
    run0 = next((r for r in tpl.findall(T_RUN) if r.findall(T_T)), None)
    cp = run0.get("charPrIDRef") if run0 is not None else "0"
    w = Writer(pkg)
    pid = w._parapr(tpl.get("paraPrIDRef"), 0, 0)
    sec = loc.secs[0]
    first = sec.find(T_P)
    idx = list(sec).index(first) + 1  # 구역 설정(secPr)이 든 첫 문단 뒤
    lines = ["한" * 10, "1234567890"] + [s + PROBE_TAIL for s in PROBE_SYMS]
    for k, text in enumerate(lines):
        para = Writer._para(tpl, pid, cp, "〔PROBE〕 " + text)
        if k >= 2:  # 기호 뒤 빈칸은 작성 시와 같은 고정폭 빈칸
            t = para.find(T_RUN).find(T_T)
            head, rest = t.text.split(" ", 1)
            symtxt, tail = rest.split(" ", 1)
            t.text = head + " " + symtxt
            fw = None
            for _ in range(FW_COUNT):
                fw = etree.SubElement(t, q("hp", "fwSpace"))
            fw.tail = tail
        sec.insert(idx + k, para)
    pkg.touch(pkg.section_names()[0])
    return len(lines)


def read_probe(pdf: str) -> dict:
    """probe 문단을 한글로 변환한 PDF 에서 기호+공백 폭을 잰다(HWPUNIT)."""
    from .image import pdf_words
    words = pdf_words(pdf)
    lines: dict[tuple, list] = {}
    for pg, t, x0, y0, x1, y1 in words:
        lines.setdefault((pg, round((y0 + y1) / 2)), []).append((x0, x1, t))
    found = {}
    for key, ws in lines.items():
        ws.sort()
        txt = " ".join(t for _, _, t in ws)
        if not txt.startswith("〔PROBE〕"):
            continue
        if len(ws) < 2:
            continue
        body = " ".join(t for _, _, t in ws[1:])
        w1 = ws[1]
        if body.startswith("한" * 10):
            found["_em"] = (w1[1] - w1[0]) / 10 * 100
            continue
        if body.startswith("1234567890"):
            found["_digit"] = (w1[1] - w1[0]) / 10 * 100
            continue
        sym = next((s for s in PROBE_SYMS if body.startswith(s.strip() + " ")), None)
        tail = next((w for w in ws[2:] if w[2].startswith(PROBE_TAIL)), None)
        if sym is None or tail is None:
            continue
        found[sym] = (tail[0] - w1[0]) * 100
    return {k: round(v) for k, v in found.items() if v}
