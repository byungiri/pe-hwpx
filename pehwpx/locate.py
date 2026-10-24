"""문서 내 위치 지정.

경로 문법 (설계서 4.1)
- 문단:        s0/p[3]                 섹션 0의 최상위 3번째 문단(0부터)
- 표:          s0/tbl[2]               섹션 0에서 문서 순서상 2번째 표(중첩 표 포함, 0부터)
- 셀:          s0/tbl[2]/r[3]/c[1]     병합을 반영한 논리 좌표(cellAddr)
- 라벨:        label:성명               '성명' 셀의 오른쪽 셀
               label:성명>down          '성명' 셀의 아래쪽 셀
               label:성명#2             같은 라벨이 여러 개일 때 2번째(1부터)
- 누름틀:      field:이름               누름틀(필드) 이름
- 자리표시자:  {{필드명}}               본문 텍스트 안의 {{...}}
- 문단 항목:   item:용도                '용 도 : 값' 형태 문단 (표 안·본문 모두)
- 문구:        contains:상기와 같이      문구가 든 셀(셀 밖이면 문단). #n 으로 n번째
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from . import q
from .package import HwpxPackage

T_P, T_RUN, T_T = q("hp", "p"), q("hp", "run"), q("hp", "t")
T_TBL, T_TR, T_TC = q("hp", "tbl"), q("hp", "tr"), q("hp", "tc")
T_SUB = q("hp", "subList")
T_ADDR, T_SPAN = q("hp", "cellAddr"), q("hp", "cellSpan")
T_TAB, T_LB = q("hp", "tab"), q("hp", "lineBreak")
T_FWS, T_NBS = q("hp", "fwSpace"), q("hp", "nbSpace")


# ---------------------------------------------------------------- 텍스트
def text_of_t(t: etree._Element) -> str:
    out = [(t.text or "").replace("\ue000", "")]
    for ch in t:
        if ch.tag == T_TAB:
            out.append("\t")
        elif ch.tag == T_LB:
            out.append("\n")
        elif ch.tag in (T_FWS, T_NBS):  # 고정폭·묶음 빈칸
            out.append(" ")
        out.append(ch.tail or "")
    return "".join(out)


def paragraph_text(p: etree._Element) -> str:
    """문단의 직속 런 텍스트(중첩 표·도형 내부 제외)."""
    return "".join(text_of_t(t) for run in p.findall(T_RUN) for t in run.findall(T_T))


def cell_paragraphs(tc: etree._Element) -> list[etree._Element]:
    sub = tc.find(T_SUB)
    return [] if sub is None else sub.findall(T_P)


def cell_text(tc: etree._Element) -> str:
    return "\n".join(paragraph_text(p) for p in cell_paragraphs(tc))


def field_value(fb: etree._Element) -> tuple[str, bool]:
    """누름틀의 (값, 입력됨 여부). 입력 전(dirty=0)에는 안내문이 저장되어 있으므로 값은 빈 문자열."""
    p = next((a for a in fb.iterancestors() if a.tag == T_P), None)
    if p is None:
        return "", False
    fid, inside, out = fb.get("id"), False, []
    for el in p.iter():
        if el is fb:
            inside = True
        elif inside and el.tag == q("hp", "fieldEnd") and el.get("beginIDRef") == fid:
            break
        elif inside and el.tag == T_T:
            out.append(text_of_t(el))
    dirty = fb.get("dirty") == "1"
    return ("".join(out) if dirty else ""), dirty


def norm(s: str) -> str:
    """라벨 비교용 정규화: 공백·전각공백·콜론 제거."""
    return re.sub(r"[\s　:：]", "", s)


# ---------------------------------------------------------------- 표 모델
@dataclass
class Cell:
    el: etree._Element
    row: int
    col: int
    rowspan: int
    colspan: int

    @property
    def text(self) -> str:
        return cell_text(self.el)


def cells_of(tbl: etree._Element) -> list[Cell]:
    out = []
    for tr in tbl.findall(T_TR):
        for tc in tr.findall(T_TC):
            a, s = tc.find(T_ADDR), tc.find(T_SPAN)
            out.append(Cell(
                tc,
                int(a.get("rowAddr", 0)) if a is not None else 0,
                int(a.get("colAddr", 0)) if a is not None else 0,
                int(s.get("rowSpan", 1)) if s is not None else 1,
                int(s.get("colSpan", 1)) if s is not None else 1,
            ))
    return out


def cell_at(tbl: etree._Element, row: int, col: int) -> Cell | None:
    """논리 좌표 (row, col)을 덮는 셀(병합 셀 포함)."""
    for c in cells_of(tbl):
        if c.row <= row < c.row + c.rowspan and c.col <= col < c.col + c.colspan:
            return c
    return None


# ---------------------------------------------------------------- 결과
@dataclass
class Target:
    kind: str          # 'paragraph' | 'cell' | 'field' | 'placeholder' | 'table'
    path: str          # 정규 경로(s0/tbl[1]/r[2]/c[3] 등)
    el: etree._Element
    section: int
    extra: dict | None = None


class LocateError(LookupError):
    pass


# ---------------------------------------------------------------- 탐색기
class Locator:
    def __init__(self, pkg: HwpxPackage):
        self.pkg = pkg
        self.secs = pkg.sections()
        self._tables = [list(sec.iter(T_TBL)) for sec in self.secs]

    # 경로 생성(역방향) ------------------------------------------
    def table_path(self, tbl: etree._Element) -> str:
        for si, tbls in enumerate(self._tables):
            for ti, t in enumerate(tbls):
                if t is tbl:
                    return f"s{si}/tbl[{ti}]"
        raise LocateError("표를 찾을 수 없음")

    def cell_path(self, tbl: etree._Element, c: Cell) -> str:
        return f"{self.table_path(tbl)}/r[{c.row}]/c[{c.col}]"

    def where(self, el: etree._Element) -> str:
        """요소가 놓인 셀 경로, 셀 밖이면 최상위 문단 경로."""
        tc = el if el.tag == T_TC else next((a for a in el.iterancestors() if a.tag == T_TC), None)
        if tc is not None:
            tbl = next(a for a in tc.iterancestors() if a.tag == T_TBL)
            cell = next(c for c in cells_of(tbl) if c.el is tc)
            return self.cell_path(tbl, cell)
        for si, sec in enumerate(self.secs):
            top = el if el.getparent() is sec else next((a for a in el.iterancestors() if a.getparent() is sec), None)
            if top is not None and top.tag == T_P:
                return f"s{si}/p[{sec.findall(T_P).index(top)}]"
        return ""

    def tables(self, section: int | None = None):
        for si, tbls in enumerate(self._tables):
            if section is not None and si != section:
                continue
            for ti, t in enumerate(tbls):
                yield si, ti, t

    # 경로 해석(정방향) ------------------------------------------
    _RE_PATH = re.compile(r"^s(\d+)/(?:p\[(\d+)\]|tbl\[(\d+)\](?:/r\[(\d+)\]/c\[(\d+)\])?)$")

    def resolve(self, spec: str) -> Target:
        spec = spec.strip()
        if spec.startswith("label:"):
            return self._by_label(spec[6:])
        if spec.startswith("field:"):
            return self._by_field(spec[6:])
        if spec.startswith("item:"):
            return self._by_item(spec[5:])
        if spec.startswith("contains:"):
            return self._by_contains(spec[9:])
        if spec.startswith("{{") and spec.endswith("}}"):
            return self._by_placeholder(spec[2:-2].strip())
        m = self._RE_PATH.match(spec)
        if not m:
            raise LocateError(f"해석할 수 없는 위치 표기: {spec}")
        si = int(m.group(1))
        if si >= len(self.secs):
            raise LocateError(f"섹션 {si} 없음")
        if m.group(2) is not None:
            ps = self.secs[si].findall(T_P)
            pi = int(m.group(2))
            if pi >= len(ps):
                raise LocateError(f"{spec}: 문단 수 {len(ps)}")
            return Target("paragraph", spec, ps[pi], si)
        ti = int(m.group(3))
        if ti >= len(self._tables[si]):
            raise LocateError(f"{spec}: 표 수 {len(self._tables[si])}")
        tbl = self._tables[si][ti]
        if m.group(4) is None:
            return Target("table", spec, tbl, si)
        c = cell_at(tbl, int(m.group(4)), int(m.group(5)))
        if c is None:
            raise LocateError(f"{spec}: 해당 좌표의 셀 없음")
        return Target("cell", self.cell_path(tbl, c), c.el, si, {"table": tbl, "cell": c})

    def _by_label(self, body: str) -> Target:
        direction, nth = "right", 1
        if "#" in body:
            body, n = body.rsplit("#", 1)
            nth = int(n)
        if ">" in body:
            body, direction = body.split(">", 1)
        want = norm(body)
        hits = []
        for si, _, tbl in self.tables():
            for c in cells_of(tbl):
                if norm(c.text) == want:
                    hits.append((si, tbl, c))
        if len(hits) < nth:
            raise LocateError(f"라벨 '{body}' 셀 없음 (발견 {len(hits)}건)")
        si, tbl, c = hits[nth - 1]
        if direction == "right":
            tgt = cell_at(tbl, c.row, c.col + c.colspan)
        elif direction == "down":
            tgt = cell_at(tbl, c.row + c.rowspan, c.col)
        else:
            raise LocateError(f"방향은 right|down: {direction}")
        if tgt is None:
            raise LocateError(f"라벨 '{body}' 의 {direction} 쪽 셀 없음")
        return Target("cell", self.cell_path(tbl, tgt), tgt.el, si, {"table": tbl, "cell": tgt, "label": c})

    def _all_paragraphs(self):
        for si, sec in enumerate(self.secs):
            for p in sec.iter(T_P):
                yield si, p

    def _by_item(self, body: str) -> Target:
        nth = 1
        if "#" in body:
            body, n = body.rsplit("#", 1)
            nth = int(n)
        lab = r"\s*".join(re.escape(ch) for ch in re.sub(r"\s", "", body))
        pat = re.compile(r"(^|[\s(（])" + lab + r"\s*[:：]")
        hits = [(si, p) for si, p in self._all_paragraphs() if pat.search(paragraph_text(p))]
        if len(hits) < nth:
            raise LocateError(f"문단 항목 '{body} :' 없음 (발견 {len(hits)}건)")
        si, p = hits[nth - 1]
        return Target("item", self.where(p) or f"item:{body}", p, si, {"label": body})

    def _by_contains(self, body: str) -> Target:
        nth = 1
        if "#" in body:
            body, n = body.rsplit("#", 1)
            nth = int(n)
        want = norm(body)
        hits, seen = [], set()
        for si, p in self._all_paragraphs():
            if want and want in norm(paragraph_text(p)):
                tc = next((a for a in p.iterancestors() if a.tag == T_TC), None)
                el = tc if tc is not None else p
                if id(el) not in seen:
                    seen.add(id(el))
                    hits.append((si, el))
        if len(hits) < nth:
            raise LocateError(f"문구 '{body}' 가 든 위치 없음 (발견 {len(hits)}건)")
        si, el = hits[nth - 1]
        if el.tag == T_TC:
            tbl = next(a for a in el.iterancestors() if a.tag == T_TBL)
            cell = next(c for c in cells_of(tbl) if c.el is el)
            return Target("cell", self.cell_path(tbl, cell), el, si, {"table": tbl, "cell": cell})
        return Target("paragraph", self.where(el), el, si)

    def _by_field(self, name: str) -> Target:
        for si, sec in enumerate(self.secs):
            for fb in sec.iter(q("hp", "fieldBegin")):
                if fb.get("name") == name:
                    p = next(a for a in fb.iterancestors() if a.tag == T_P)
                    return Target("field", f"field:{name}", fb, si, {"paragraph": p})
        raise LocateError(f"누름틀 '{name}' 없음")

    def _by_placeholder(self, name: str) -> Target:
        token = "{{" + name + "}}"
        for si, sec in enumerate(self.secs):
            for p in sec.iter(T_P):
                if token in paragraph_text(p):
                    return Target("placeholder", token, p, si, {"token": token})
        raise LocateError(f"자리표시자 {token} 없음")
