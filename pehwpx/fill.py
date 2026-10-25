"""채움 (설계서 4.2).

채움 항목(JSON/YAML의 fill 목록 한 줄)
  {"at": "label:직위", "value": "이사"}                       셀 전체 교체 (\n 은 문단 분리)
  {"at": "s0/tbl[0]/r[6]/c[0]", "after": "용도", "value": "..."} 대상 안 '용 도 : 값' 의 값만 교체
  {"at": "s0/tbl[0]/r[6]/c[0]", "date": "2026-10-24"}          대상 안 첫 날짜 표기의 숫자만 교체
  {"at": "field:소속", "value": "..."}                          누름틀 값
  {"at": "{{주소}}", "value": "..."}                            자리표시자 치환
  {"at": "s0/p[3]", "value": "..."}                             문단 전체 교체
  {"at": "item:용도", "value": "..."}                           '용 도 :' 문단의 값만 교체
  {"at": "contains:상기와 같이", "date": "today"}                 그 문구가 든 셀의 첫 날짜 (빈칸 날짜 '2025.  2.   .' 포함)
  {"at": "contains:동의함", "check": "동의함"}                     '□ 동의함' → '■ 동의함'
  {"at": "contains:(소속)", "slot": "(소속)", "value": "..."}         '(소속)      (성명)' 처럼 공백으로 자리를 비운 서명란:
                                                                  라벨 뒤 공백 폭 안에 값을 넣고 남은 폭은 공백으로 유지
  {"rows": "s0/tbl[3]/r[17]", "cols": [1, 2, 5, 8], "data": [[...], ...]}  반복행 (rows.py 참조)
  "value" 대신 "from": "person.name" 을 쓰면 --data JSON 에서 값을 읽는다.
  셀 채움에 "fit": true (또는 채움 파일 최상위 "fit": true) 를 주면, 값이 칸 폭을 넘을 때 다음 순서로 맞춘다(v0.9.3).
    1) 칸 높이에 여유가 있어 원래 크기로 줄바꿈해도 칸 안에 들어가면 글자를 줄이지 않는다("fit_wrap": false 로 끔).
    2) 원래 크기 그대로 자간만 -2%씩 최대 -10%까지 좁힌다.
    3) 그래도 넘치면 0.5pt씩 줄이되 하한은 원래 크기의 90%("fit_min_ratio")와 10pt("fit_min_pt") 중 큰 값.
       각 크기에서 자간을 함께 좁혀 축소 폭을 최소로 한다.
    4) 하한까지 줄여도 안 되면 원래 크기로 두어 줄바꿈되게 하고 결과에 '문구 축약 검토'로 표시한다
       (줄을 나눌 위치는 값에 \n 으로 지정 가능).
  필요한 글자모양은 header 끝에 추가하며, 기존 글자모양은 바꾸지 않는다.
  값을 \n 으로 여러 줄로 나눈 셀은 줄 간격을 "line_pct"(기본 115%, fit 사용 시 자동)로 좁혀 두 줄 사이가
  벌어지지 않게 한다. 문단모양도 header 끝에 변형을 추가하는 방식이다.

공통 규칙
- 바뀐 문단의 첫 글자모양(charPr)·문단모양(paraPr)을 그대로 쓴다.
- 견본 안내 글자(회색 등 흐린 색 글자, 예: '홍길동', '1970. 07. 07.')를 바꾼 경우, 색만 다른 검은색
  글자모양이 문서에 있으면 그것으로 바꿔 본문 글자로 만든다(결과에 '안내색 해제' 표시).
- 텍스트를 바꾼 문단은 줄 배치 캐시(hp:linesegarray)를 지워 한글이 다시 계산하게 한다
  (캐시를 남기면 긴 텍스트가 한 줄에 압축됨: docs/TEST_REPORT.md 2절).
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass

from lxml import etree

from . import q
from .locate import (T_P, T_RUN, T_T, LocateError, Locator, cell_paragraphs,
                     cells_of, paragraph_text, text_of_t)
from .package import HwpxPackage
from .textforms import (BOX_ON, disp_width, find_box, find_item, iter_dates,
                        parse_date, render_date, render_item)

T_LSA = q("hp", "linesegarray")
T_CTRL = q("hp", "ctrl")
T_FB, T_FE = q("hp", "fieldBegin"), q("hp", "fieldEnd")

def has_date(text: str) -> bool:
    return next(iter_dates(text), None) is not None


class FillError(ValueError):
    pass


@dataclass
class Applied:
    spec: str
    kind: str
    where: str
    before: str
    after: str


# ================================================================ 문단 단위 조작
def _ts(p: etree._Element) -> list[etree._Element]:
    return [t for run in p.findall(T_RUN) for t in run.findall(T_T)]


def drop_lineseg(p: etree._Element) -> None:
    s = p.find(T_LSA)
    if s is not None:
        p.remove(s)


def set_paragraph(p: etree._Element, text: str) -> None:
    """문단 텍스트 전체 교체. 그림·표 등 개체(ctrl, pic 등)가 든 런은 보존한다."""
    ts = _ts(p)
    if ts:
        first = ts[0]
        for ch in list(first):
            first.remove(ch)
        first.text = text
        for t in ts[1:]:
            t.getparent().remove(t)
    else:
        runs = p.findall(T_RUN)
        if runs:
            run = runs[0]
        else:
            run = etree.SubElement(p, T_RUN)
            run.set("charPrIDRef", "0")
            p.remove(run)
            p.insert(0, run)
        t = etree.SubElement(run, T_T)
        t.text = text
    drop_lineseg(p)


def replace_span(p: etree._Element, start: int, end: int, new: str) -> None:
    """문단 텍스트의 [start, end) 구간을 new 로 바꾼다. 여러 런에 걸쳐도 처리한다.
    탭·줄바꿈·고정폭 빈칸 같은 글자 요소가 섞인 런도 그 요소를 건드리지 않는 구간이면 바꾼다."""
    from .locate import T_FWS, T_LB, T_NBS, T_TAB
    one = (T_TAB, T_LB, T_FWS, T_NBS)
    segs = []  # (종류, 요소, 길이)
    for t in _ts(p):
        segs.append(("text", t, len((t.text or "").replace("\ue000", ""))))
        for ch in t:
            segs.append(("obj", ch, 1 if ch.tag in one else 0))
            segs.append(("tail", ch, len((ch.tail or "").replace("\ue000", ""))))
    pos, placed = 0, False
    for kind, el, n in segs:
        a, b = pos, pos + n
        pos = b
        if kind == "obj":
            if n and start < b and end > a:
                raise FillError("탭·강제 줄바꿈·고정폭 빈칸 글자를 지우는 치환은 할 수 없음 (문단 전체 교체를 사용)")
            continue
        hit = (a < end and b > start) or (start == end and a <= start <= b and not placed)
        if not hit:
            continue
        raw = ((el.text if kind == "text" else el.tail) or "").replace("\ue000", "")
        lo, hi = max(start - a, 0), min(end - a, len(raw))
        val = raw[:lo] + (new if not placed else "") + raw[hi:]
        placed = True
        if kind == "text":
            el.text = val
        else:
            el.tail = val
    if not placed:
        raise FillError("치환 구간을 찾지 못함")
    drop_lineseg(p)


def _fmt_like(orig: str, n: int, pad: bool = False) -> str:
    """원본 표기 방식 유지: 문서가 0 채움(07, 01)을 쓰면 두 자리로 맞춘다."""
    return f"{n:02d}" if (pad or orig.startswith("0")) and n < 10 else str(n)


# ================================================================ 채움기
FIT_KEYS = ("fit", "fit_min_pt", "fit_min_ratio", "fit_wrap")


class Filler:
    def __init__(self, pkg: HwpxPackage):
        self.pkg = pkg
        self.loc = Locator(pkg)
        self.applied: list[Applied] = []
        self.allowed: set[str] = set()
        self._dirty_sections: set[int] = set()

    # ------------------------------------------------------------ 진입점
    def apply(self, item: dict, data: dict | None = None) -> Applied:
        if "rows" in item:
            return self._rows(item, data)
        spec = item["at"]
        value = self._value(item, data)
        try:
            tgt = self.loc.resolve(spec)
        except LocateError as e:
            raise FillError(str(e)) from e
        if "check" in item:
            res = self._check(tgt, item["check"])
        elif "slot" in item:
            res = self._slot(tgt, item["slot"], value)
        elif "after" in item:
            res = self._after(tgt, item["after"], value)
        elif tgt.kind == "item" and "date" not in item:
            res = self._after(tgt, tgt.extra["label"], value)
        elif "date" in item:
            res = self._date(tgt, item["date"])
        elif tgt.kind == "cell":
            res = self._cell(tgt, value)
        elif tgt.kind == "field":
            res = self._field(tgt, value)
        elif tgt.kind == "placeholder":
            res = self._placeholder(tgt, value)
        elif tgt.kind == "paragraph":
            before = paragraph_text(tgt.el)
            set_paragraph(tgt.el, value)
            res = Applied(spec, "문단", tgt.path, before, value)
        else:
            raise FillError(f"{spec}: 표 전체는 채울 수 없음 (셀 경로를 지정)")
        res.spec = spec
        if self._unguide(tgt):
            res.kind += " +안내색 해제"
        if (item.get("fit") and tgt.kind == "cell" and value
                and not any(k in item for k in ("slot", "after", "date", "check"))):
            note = self._fit(tgt.el, float(item.get("fit_min_pt", 10)),
                             float(item.get("fit_min_ratio", 0.9)), bool(item.get("fit_wrap", True)))
            if note:
                res.kind += f" +{note}"
        if tgt.kind == "cell" and "\n" in value and (item.get("fit") or "line_pct" in item):
            pct = int(item.get("line_pct", 115))
            if self._tighten(tgt.el, pct):
                res.kind += f" +줄간격 {pct}%"
        self.applied.append(res)
        self.allowed.add(res.where)
        self._dirty_sections.add(tgt.section)
        return res

    # ------------------------------------------------------------ 반복행
    def _rows(self, item: dict, data: dict | None) -> Applied:
        from . import rows as R
        try:
            tpath, start = R.parse_start(item["rows"])
            tgt = self.loc.resolve(tpath)
        except (R.RowsError, LocateError) as e:
            raise FillError(str(e)) from e
        tbl = tgt.el
        recs = item.get("data")
        if recs is None and "from" in item:
            cur = data or {}
            for k in item["from"].split("."):
                if not isinstance(cur, dict) or k not in cur:
                    raise FillError(f"데이터에 '{item['from']}' 없음")
                cur = cur[k]
            recs = cur
        if not isinstance(recs, list):
            raise FillError(f"{item['rows']}: data(목록) 또는 from 이 필요함")
        cols = item.get("cols")
        if not cols:
            raise FillError(f"{item['rows']}: cols(값을 넣을 열 목록)가 필요함")
        keyed = isinstance(cols, dict)
        try:
            colset = set(cols.values()) if keyed else set(cols)
            block = R.find_block(tbl, start, item.get("block"), colset)
            numbering = R.number_cols(tbl, block, colset)
        except R.RowsError as e:
            raise FillError(str(e)) from e
        cap, n = len(block), len(recs)
        mode = item.get("overflow", "error")
        before = R.row_snapshot(tbl)
        note, overflow_recs = "", []
        if n > cap:
            if mode == "grow":
                R.grow(tbl, block[-1], n - cap)
                note = f"+{n - cap}행 추가"
            elif mode == "annex":
                overflow_recs = recs[cap - 1:]
                recs = recs[:cap - 1]
                note = f"{len(overflow_recs)}건 별지"
            else:
                raise FillError(f"{item['rows']}: 자료 {n}건 > 반복 구간 {cap}행. "
                                "행 추가를 허용하면 overflow=grow, 별지로 돌리면 overflow=annex")
        elif n < cap and item.get("trim") and n > 0:
            R.shrink(tbl, block[-1], cap - n)
            note = f"-{cap - n}행 삭제"
        n_after = n if (n > cap and mode == "grow") or (0 < n < cap and item.get("trim")) else cap
        # 칸 채우기 (일반 셀 채움과 같은 규칙: 서식 승계·안내색 해제·fit)
        common = {k: item[k] for k in FIT_KEYS + ("line_pct",) if k in item}
        filled = 0
        for i, rec in enumerate(recs):
            pairs = ([(col, rec.get(key, "")) for key, col in cols.items()] if keyed and isinstance(rec, dict)
                     else list(zip(cols, rec)))
            for col, val in pairs:
                self.apply({**common, "at": f"{tpath}/r[{start + i}]/c[{col}]", "value": "" if val is None else str(val)})
                filled += 1
        for col, lastno in numbering.items():  # 순번 열 이어 매기기(늘린 행)
            for i in range(cap, n_after):
                self.apply({"at": f"{tpath}/r[{start + i}]/c[{col}]", "value": str(lastno + i - cap + 1)})
        if overflow_recs:
            first_col = (list(cols.values()) if keyed else cols)[0]
            self.apply({"at": f"{tpath}/r[{start + cap - 1}]/c[{first_col}]",
                        "value": item.get("annex_text", "별지 참조")})
        bad = R.check_outside(before, R.row_snapshot(tbl), start, cap, n_after)
        if bad:
            raise FillError(f"{item['rows']}: 반복 구간 밖 행이 바뀜 {bad[:5]}")
        # 변경 허용 범위: 표 수준(행 수·높이), 구간 시작 이후 모든 칸(행 번호 이동), 세로 병합 칸
        self.allowed.add(tpath + "#table")
        for c in cells_of(tbl):
            if c.row >= start or c.row + c.rowspan - 1 >= start:
                self.allowed.add(self.loc.cell_path(tbl, c))
        p = next((a for a in tbl.iterancestors() if a.tag == T_P and a.getparent() in self.loc.secs), None)
        if p is not None:
            self.allowed.add(self.loc.where(p))
        self._dirty_sections.add(tgt.section)
        res = Applied(item["rows"], f"반복행(r[{block[0]}]~r[{block[-1]}], {n}건/구간 {cap}행" + (f", {note}" if note else "")
                      + (", 순번 이어짐" if numbering and n_after > cap else "") + ")",
                      tpath, f"{cap}행", f"{n_after}행, 칸 {filled}개")
        res.overflow = overflow_recs
        self.applied.append(res)
        return res

    # ------------------------------------------------------------ 견본 안내 글자색
    def _charprs(self) -> dict:
        if not hasattr(self, "_cp"):
            self._cp = {}
            name = next((n for n in self.pkg.names() if n.lower().endswith("header.xml")), None)
            if name:
                for cp in self.pkg.xml(name).getroot().iter(q("hh", "charPr")):
                    self._cp[cp.get("id")] = cp
        return self._cp

    @staticmethod
    def _is_guide(color: str | None) -> bool:
        """흐린 회색(#808080~#DDDDDD, R=G=B) 글자를 견본 안내 글자로 본다."""
        if not color or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            return False
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        return r == g == b and 0x80 <= r <= 0xDD

    def _black_twin(self, cid: str) -> str | None:
        cps = self._charprs()
        src = cps.get(cid)
        if src is None or not self._is_guide(src.get("textColor")):
            return None

        def key(el):
            c = copy.deepcopy(el)
            c.attrib.pop("id", None)
            c.attrib.pop("textColor", None)
            return etree.tostring(c)

        k = key(src)
        for oid, el in cps.items():
            if oid != cid and el.get("textColor", "").upper() == "#000000" and key(el) == k:
                return oid
        return None

    def _unguide(self, tgt) -> bool:
        if tgt.kind == "cell":
            ps = cell_paragraphs(tgt.el)
        elif tgt.kind in ("paragraph", "placeholder", "item"):
            ps = [tgt.el]
        else:
            return False
        changed = False
        for p in ps:
            if p.find(T_LSA) is not None:
                continue  # 이번에 바꾸지 않은 문단(줄 배치 캐시가 남아 있음)
            for run in p.findall(T_RUN):
                if not any((t.text or "").strip() for t in run.findall(T_T)):
                    continue
                twin = self._black_twin(run.get("charPrIDRef"))
                if twin:
                    run.set("charPrIDRef", twin)
                    changed = True
        return changed

    # ------------------------------------------------------------ 칸 폭 맞춤
    @staticmethod
    def _est_width(text: str, height: int, ratio: int) -> float:
        """대략 폭(HWPUNIT). 전각 1em, 반각(영문·숫자·기호) 0.65em, 공백 0.5em, 장평 반영."""
        em = sum(1.0 if ord(ch) > 0x2000 else (0.5 if ch == " " else 0.65) for ch in text)
        return em * height * ratio / 100

    def _charpr_variant(self, src_id: str, height: int, spacing: int = 0) -> str:
        """src 글자모양에서 크기(height)·자간(spacing %, 7개 언어 공통)만 바꾼 글자모양 id (없으면 header 끝에 추가)."""
        cps = self._charprs()
        src = cps[src_id]

        def variant(el):
            c = copy.deepcopy(el)
            c.set("height", str(height))
            sp = c.find(q("hh", "spacing"))
            if sp is not None and spacing:
                for k in list(sp.attrib):
                    sp.set(k, str(spacing))
            return c

        def key(el):
            c = copy.deepcopy(el)
            c.attrib.pop("id", None)
            return etree.tostring(c)

        want = key(variant(src))
        for oid, el in cps.items():
            if key(el) == want:
                return oid
        new = variant(src)
        nid = str(max(int(i) for i in cps) + 1)
        new.set("id", nid)
        parent = src.getparent()
        parent.append(new)
        if parent.get("itemCnt"):
            parent.set("itemCnt", str(len(parent.findall(q("hh", "charPr")))))
        cps[nid] = new
        name = next(n for n in self.pkg.names() if n.lower().endswith("header.xml"))
        self.pkg.touch(name)
        return nid

    def _line_pct(self, p) -> int:
        """문단의 줄 간격(%) — 고정값 등 비율이 아니면 160 으로 본다."""
        name = next(n for n in self.pkg.names() if n.lower().endswith("header.xml"))
        root = self.pkg.xml(name).getroot()
        pid = p.get("paraPrIDRef")
        for pp in root.iter(q("hh", "paraPr")):
            if pp.get("id") == pid:
                for ls in pp.iter(q("hh", "lineSpacing")):
                    if ls.get("type", "PERCENT") == "PERCENT":
                        return int(ls.get("value", 160))
                break
        return 160

    def _fit(self, tc, min_pt: float, min_ratio: float = 0.9, wrap: bool = True) -> str | None:
        """칸 폭 맞춤(v0.9.3). 순서: ① 칸 높이 안 줄바꿈 → ② 원래 크기에서 자간만(-2%씩, 최대 -10%)
        → ③ 0.5pt씩 축소(하한 = max(min_pt, 원래 크기 × min_ratio)) + 자간 → ④ 불가 시 원래 크기로 줄바꿈.
        실사용 의견(2026-10-25): 글자를 너무 작게 줄여 다시 편집해야 했음 → 줄바꿈·자간 우선, 축소 하한."""
        sz, mg = tc.find(q("hp", "cellSz")), tc.find(q("hp", "cellMargin"))
        lr = (int(mg.get("left", 141)) + int(mg.get("right", 141))) if mg is not None else 282
        tb = (int(mg.get("top", 141)) + int(mg.get("bottom", 141))) if mg is not None else 282
        avail = int(sz.get("width")) - lr
        avail_h = int(sz.get("height", 0)) - tb
        limit = avail * 0.95
        cps = self._charprs()
        ps = cell_paragraphs(tc)
        notes = []
        spacings = (-2, -4, -6, -8, -10)
        for p in ps:
            runs = [r for r in p.findall(T_RUN) if any((t.text or "") for t in r.findall(T_T))]
            if len(runs) != 1:
                continue
            run = runs[0]
            cid = run.get("charPrIDRef")
            src = cps.get(cid)
            if src is None:
                continue
            h0 = int(src.get("height"))
            ratio_el = src.find(q("hh", "ratio"))
            ratio = int(ratio_el.get("hangul", 100)) if ratio_el is not None else 100
            text = paragraph_text(p)
            w0 = self._est_width(text, h0, ratio)
            if w0 <= limit:
                continue
            # ① 칸 높이 안에서 원래 크기로 줄바꿈 가능하면 그대로 둔다(문단 1개인 칸만)
            if wrap and len(ps) == 1 and avail_h > 0:
                lines = -(-w0 // limit)  # 올림
                if lines * h0 * self._line_pct(p) / 100 <= avail_h:
                    notes.append(f"원래 크기 {int(lines)}줄(칸 높이 안)")
                    continue
            floor = max(int(min_pt * 100), int(-(-h0 * min_ratio // 50)) * 50)
            pick = None
            # ② 원래 크기에서 자간만
            for sp in spacings:
                if w0 * (1 + sp / 100) <= limit:
                    pick = (h0, sp)
                    break
            # ③ 0.5pt씩 축소(하한까지), 각 크기에서 필요한 최소 자간
            h = h0
            while pick is None and h - 50 >= floor:
                h -= 50
                w = self._est_width(text, h, ratio)
                for sp in (0,) + spacings:
                    if w * (1 + sp / 100) <= limit:
                        pick = (h, sp)
                        break
            if pick is None:
                notes.append(f"한 줄 불가(하한 {floor / 100:g}pt), 원래 크기로 줄바꿈 — 문구 축약 검토")
                continue
            run.set("charPrIDRef", self._charpr_variant(cid, pick[0], pick[1]))
            size = f"{pick[0] / 100:g}pt" if pick[0] != h0 else f"{h0 / 100:g}pt 유지"
            notes.append(size + (f" 자간{pick[1]}%" if pick[1] else ""))
        return ", ".join(notes) or None

    # ------------------------------------------------------------ 여러 줄 셀 줄 간격
    def _parapr_with_spacing(self, src_id: str, pct: int) -> str:
        name = next(n for n in self.pkg.names() if n.lower().endswith("header.xml"))
        root = self.pkg.xml(name).getroot()
        pps = {e.get("id"): e for e in root.iter(q("hh", "paraPr"))}
        src = pps[src_id]

        def variant(el):
            c = copy.deepcopy(el)
            for ls in c.iter(q("hh", "lineSpacing")):
                if ls.get("type", "PERCENT") == "PERCENT":
                    ls.set("value", str(pct))
            return c

        def key(el):
            c = copy.deepcopy(el)
            c.attrib.pop("id", None)
            return etree.tostring(c)

        want = key(variant(src))
        for oid, el in pps.items():
            if key(el) == want:
                return oid
        new = variant(src)
        nid = str(max(int(i) for i in pps) + 1)
        new.set("id", nid)
        parent = src.getparent()
        parent.append(new)
        if parent.get("itemCnt"):
            parent.set("itemCnt", str(len(parent.findall(q("hh", "paraPr")))))
        self.pkg.touch(name)
        return nid

    def _tighten(self, tc, pct: int) -> bool:
        ps = cell_paragraphs(tc)
        if len(ps) < 2:
            return False
        changed = False
        for p in ps:
            cur = p.get("paraPrIDRef")
            nid = self._parapr_with_spacing(cur, pct)
            if nid != cur:
                p.set("paraPrIDRef", nid)
                changed = True
        return changed

    def finish(self) -> None:
        names = self.pkg.section_names()
        for si in self._dirty_sections:
            self.pkg.touch(names[si])

    # ------------------------------------------------------------ 값
    @staticmethod
    def _value(item: dict, data: dict | None) -> str:
        if "value" in item:
            return str(item["value"])
        if "from" in item:
            cur = data or {}
            for k in item["from"].split("."):
                if not isinstance(cur, dict) or k not in cur:
                    raise FillError(f"데이터에 '{item['from']}' 없음")
                cur = cur[k]
            return str(cur)
        if "date" in item or "check" in item:
            return ""
        raise FillError(f"{item.get('at')}: value 또는 from 이 필요함")

    # ------------------------------------------------------------ 종류별
    def _cell(self, tgt, value: str) -> Applied:
        tc = tgt.el
        before = "\n".join(paragraph_text(p) for p in cell_paragraphs(tc))
        if before == value:
            return Applied("", "셀(동일, 변경 없음)", tgt.path, before, value)
        ps = cell_paragraphs(tc)
        lines = value.split("\n")
        # 개체(그림·표·누름틀)가 든 문단은 지우지 않는다
        for p in ps[len(lines):]:
            if any(ch.tag != T_T for r in p.findall(T_RUN) for ch in r):
                raise FillError(f"{tgt.path}: 개체가 든 문단이 있어 셀 전체 교체 불가 (after/date 방식 사용)")
        for i, line in enumerate(lines):
            if i < len(ps):
                set_paragraph(ps[i], line)
            else:
                np_ = copy.deepcopy(ps[-1])
                ps[-1].addnext(np_)
                set_paragraph(np_, line)
                ps.append(np_)
        for p in ps[len(lines):]:
            p.getparent().remove(p)
        return Applied("", "셀", tgt.path, before, value)

    def _paragraphs_of(self, tgt) -> list[etree._Element]:
        if tgt.kind == "cell":
            return cell_paragraphs(tgt.el)
        if tgt.kind in ("paragraph", "placeholder", "item"):
            return [tgt.el]
        raise FillError(f"{tgt.path}: after/date 는 셀 또는 문단에만 사용")

    def _after(self, tgt, label: str, value: str) -> Applied:
        for p in self._paragraphs_of(tgt):
            sp = find_item(paragraph_text(p), label)
            if sp is None:
                continue
            if sp.value == value:
                return Applied("", f"문단 항목({label}, 동일·변경 없음)", self.loc.where(p), value, value)
            replace_span(p, sp.start, sp.end, render_item(sp, value))
            return Applied("", f"문단 항목({label})", self.loc.where(p), sp.value or "(빈칸)", value)
        raise FillError(f"{tgt.path}: '{label} :' 항목을 찾지 못함")

    def _check(self, tgt, label: str) -> Applied:
        for p in self._paragraphs_of(tgt):
            i = find_box(paragraph_text(p), label)
            if i is None:
                continue
            cur = paragraph_text(p)[i]
            if cur == BOX_ON:
                return Applied("", f"체크({label}, 이미 체크됨)", self.loc.where(p), cur, cur)
            replace_span(p, i, i + 1, BOX_ON)
            return Applied("", f"체크({label})", self.loc.where(p), f"{cur} {label}", f"{BOX_ON} {label}")
        raise FillError(f"{tgt.path}: '□ {label}' 체크 상자를 찾지 못함")

    def _slot(self, tgt, label: str, value: str) -> Applied:
        """'(소속)                (성명)' 처럼 라벨 뒤 공백으로 비워 둔 자리에 값을 넣는다.
        라벨 뒤 공백 폭(반각 기준) 안에 ' 값'을 넣고 남은 폭은 공백으로 채워 뒤 문구 위치를 유지한다."""
        for p in self._paragraphs_of(tgt):
            text = paragraph_text(p)
            i = text.find(label)
            if i < 0:
                continue
            s = i + len(label)
            e = s
            while e < len(text) and text[e] == " ":
                e += 1
            gap = e - s
            tail_exists = e < len(text) and text[e:].strip() != ""
            need = 1 + disp_width(value) + (1 if tail_exists else 0)
            new = " " + value + " " * max(1 if tail_exists else 0, gap - 1 - disp_width(value))
            if text[s:e] == new[:e - s] and text[s:].startswith(new):
                return Applied("", f"자리({label}, 동일·변경 없음)", self.loc.where(p), value, value)
            replace_span(p, s, e, new)
            note = "" if need <= gap else f", 폭 {need - gap}칸 초과"
            return Applied("", f"자리({label}{note})", self.loc.where(p), "(빈칸)", value)
        raise FillError(f"{tgt.path}: '{label}' 문구를 찾지 못함")

    def _date(self, tgt, iso) -> Applied:
        d = parse_date(iso)
        for p in self._paragraphs_of(tgt):
            for m, style in iter_dates(paragraph_text(p)):
                new = render_date(m, style, d)
                if m.group(0) == new:
                    return Applied("", "날짜(동일, 변경 없음)", self.loc.where(p), new, new)
                replace_span(p, m.start(), m.end(), new)
                return Applied("", "날짜", self.loc.where(p), m.group(0), new)
        raise FillError(f"{tgt.path}: 날짜 표기(YYYY 년 M 월 D 일 / YYYY. M. D., 빈칸 포함)를 찾지 못함")

    def _field(self, tgt, value: str) -> Applied:
        fb = tgt.el
        p = tgt.extra["paragraph"]
        fid = fb.get("id")
        before = paragraph_text(p)
        from .locate import field_value
        cur, filled = field_value(fb)
        if filled and cur == value:
            return Applied("", "누름틀(동일, 변경 없음)", self.loc.where(p), cur, value)
        ctrl = fb.getparent()
        run = ctrl.getparent()
        inside, doomed_t, end_found = False, [], False
        for el in p.iter():
            if el is fb:
                inside = True
            elif inside and el.tag == T_FE and el.get("beginIDRef") == fid:
                end_found = True
                break
            elif inside and el.tag == T_T:
                doomed_t.append(el)
        if not end_found:
            raise FillError(f"{tgt.path}: 누름틀 끝 표시를 같은 문단에서 찾지 못함")
        for t in doomed_t:
            parent = t.getparent()
            parent.remove(t)
            if parent.tag == T_RUN and len(parent) == 0 and parent is not run:
                parent.getparent().remove(parent)
        t = etree.Element(T_T)
        t.text = value
        run.insert(list(run).index(ctrl) + 1, t)
        fb.set("dirty", "1")
        drop_lineseg(p)
        return Applied("", "누름틀", self.loc.where(p), before, value)

    def _placeholder(self, tgt, value: str) -> Applied:
        p, token = tgt.el, tgt.extra["token"]
        s = paragraph_text(p)
        i = s.index(token)
        replace_span(p, i, i + len(token), value)
        return Applied("", "자리표시자", self.loc.where(p), token, value)


def load_map(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if path.endswith((".yaml", ".yml")):
        import yaml  # 선택 의존성
        doc = yaml.safe_load(txt)
    else:
        import json
        doc = json.loads(txt)
    items = doc.get("fill", doc) if isinstance(doc, dict) else doc
    if not isinstance(items, list):
        raise FillError("채움 파일 형식: {\"fill\": [ {...}, ... ]}")
    if isinstance(doc, dict):  # 최상위 공통 옵션(fit 관련)을 각 항목 기본값으로
        common = {k: doc[k] for k in FIT_KEYS if k in doc}
        items = [{**common, **it} for it in items]
    return items
