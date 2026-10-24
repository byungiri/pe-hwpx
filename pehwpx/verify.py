"""검증: 구조 무결성과 원본 대비 변경 범위 diff (설계서 4.7)."""

from __future__ import annotations

import difflib
import re

import zipfile
from dataclasses import dataclass, field

from lxml import etree

from . import NS
from .package import MIMETYPE, HwpxPackage

# 저장 시 한글이 다시 만드는 미리보기는 변경 범위 판정에서 제외한다.
INFORMATIONAL = {"Preview/PrvText.txt", "Preview/PrvImage.png"}


# ================================================================ 구조 검증
def check_structure(path: str) -> list[str]:
    """문제 목록을 돌려준다. 빈 목록이면 통과."""
    errs: list[str] = []
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        return [f"ZIP 아님: {e}"]
    with zf:
        infos = zf.infolist()
        if not infos or infos[0].filename != "mimetype":
            errs.append("mimetype 이 첫 항목이 아님")
        else:
            if infos[0].compress_type != zipfile.ZIP_STORED:
                errs.append("mimetype 이 압축되어 있음(비압축이어야 함)")
            if zf.read("mimetype") != MIMETYPE:
                errs.append(f"mimetype 값 이상: {zf.read('mimetype')!r}")
        bad = zf.testzip()
        if bad:
            errs.append(f"CRC 오류: {bad}")
        names = set(zf.namelist())
        for need in ("Contents/content.hpf", "Contents/header.xml", "META-INF/container.xml", "version.xml"):
            if need not in names:
                errs.append(f"필수 항목 없음: {need}")
        for n in names:
            if n.endswith(".xml") or n.endswith(".hpf") or n.endswith(".rdf"):
                try:
                    etree.fromstring(zf.read(n))
                except etree.XMLSyntaxError as e:
                    errs.append(f"XML 오류 {n}: {e}")
        if "Contents/content.hpf" in names:
            hpf = etree.fromstring(zf.read("Contents/content.hpf"))
            hrefs = set()
            for it in hpf.iter("{%s}item" % NS["opf"]):
                h = it.get("href", "")
                hrefs.add(h)
                if h and h not in names:
                    errs.append(f"매니페스트 항목 파일 없음: {h}")
            for n in names:
                if n.startswith("BinData/") and n not in hrefs:
                    errs.append(f"매니페스트 미등록 바이너리: {n}")
    return errs


# ================================================================ 변경 범위 diff
@dataclass
class Change:
    part: str
    xpath: str
    what: str
    locpath: str = ""


@dataclass
class DiffReport:
    changes: list[Change] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    informational: list[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not (self.changes or self.added or self.removed)


def _compare(a: etree._Element, b: etree._Element, path: str, out: list, part: str, tree_a) -> None:
    if a.tag != b.tag:
        out.append(Change(part, path, f"태그 변경 {etree.QName(a).localname} → {etree.QName(b).localname}"))
        return
    if dict(a.attrib) != dict(b.attrib):
        keys = sorted(set(a.attrib) | set(b.attrib))
        diff = [k for k in keys if a.get(k) != b.get(k)]
        out.append(Change(part, path, "속성 변경: " + ", ".join(f"{etree.QName(k).localname}={a.get(k)!r}→{b.get(k)!r}" for k in diff)))
    if (a.text or "") != (b.text or ""):
        out.append(Change(part, path, f"텍스트 {(a.text or '')[:30]!r} → {(b.text or '')[:30]!r}"))
    if (a.tail or "") != (b.tail or ""):
        out.append(Change(part, path, "꼬리 텍스트 변경"))
    ca, cb = list(a), list(b)
    if len(ca) != len(cb):
        out.append(Change(part, path, f"하위 요소 수 {len(ca)} → {len(cb)}"))
        # 추가·삭제가 있으면 같은 요소끼리 맞춘 뒤(순서 정렬) 나머지만 비교한다 — 문단·행 삽입 후 뒤쪽이 밀려도 오검출 없음
        ha = [etree.tostring(x) for x in ca]
        hb = [etree.tostring(y) for y in cb]
        sm = difflib.SequenceMatcher(None, ha, hb, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            if op == "replace" and i2 - i1 == j2 - j1:
                for k in range(i2 - i1):
                    _compare(ca[i1 + k], cb[j1 + k], f"{path}/{etree.QName(cb[j1 + k]).localname}[{j1 + k}]", out, part, tree_a)
                continue
            for j in range(j1, j2):
                out.append(Change(part, f"{path}/{etree.QName(cb[j]).localname}[{j}]", "요소 추가"))
            if i2 > i1:
                out.append(Change(part, path, f"하위 요소 {i2 - i1}개 삭제"))
        return
    for i, (x, y) in enumerate(zip(ca, cb)):
        _compare(x, y, f"{path}/{etree.QName(x).localname}[{i}]", out, part, tree_a)


def diff(original: str, result: str) -> DiffReport:
    rep = DiffReport()
    za, zb = zipfile.ZipFile(original), zipfile.ZipFile(result)
    with za, zb:
        na, nb = set(za.namelist()), set(zb.namelist())
        rep.added = sorted(nb - na)
        rep.removed = sorted(na - nb)
        for n in sorted(na & nb):
            da, db = za.read(n), zb.read(n)
            if da == db:
                continue
            if n in INFORMATIONAL:
                rep.informational.append(n)
                continue
            if n.endswith((".xml", ".hpf", ".rdf")):
                ra, rb = etree.fromstring(da), etree.fromstring(db)
                before = len(rep.changes)
                _compare(ra, rb, etree.QName(ra).localname, rep.changes, n, None)
                if len(rep.changes) == before:
                    # 노드 동일, 바이트만 다름(선언부·이스케이프 표기 차이)
                    rep.informational.append(n + " (직렬화 표기만 상이)")
            else:
                rep.changes.append(Change(n, "", "바이너리 내용 변경"))
    _attach_locpaths(rep, result)
    return rep


def _attach_locpaths(rep: DiffReport, result: str) -> None:
    """섹션 변경 항목에 사람이 읽는 위치(s0/tbl[1]/r[2]/c[3] 또는 s0/p[4])를 붙인다."""
    sec_changes = [c for c in rep.changes if c.part.startswith("Contents/section")]
    if not sec_changes:
        return
    pkg = HwpxPackage.open(result)
    from .locate import Locator, T_TBL, T_TC, T_P, cells_of
    loc = Locator(pkg)
    names = pkg.section_names()
    for ch in sec_changes:
        si = names.index(ch.part) if ch.part in names else -1
        if si < 0:
            continue
        el = _walk(pkg.xml(ch.part).getroot(), ch.xpath)
        if el is None:
            continue
        if el is loc.secs[si]:  # 본문 문단 추가·삭제(구역 수준)
            ch.locpath = f"s{si}#section"
            continue
        near = next((a for a in [el, *el.iterancestors()] if a.tag in (T_TC, T_TBL)), None)
        if near is not None and near.tag == T_TBL:  # 표 자체·행(tr) 수준 변경(행 추가·삭제, 행 수, 높이)
            ch.locpath = loc.table_path(near) + "#table"
            continue
        tc = near
        if tc is not None:
            tbl = next(a for a in tc.iterancestors() if a.tag == T_TBL)
            cell = next(c for c in cells_of(tbl) if c.el is tc)
            ch.locpath = loc.cell_path(tbl, cell)
            continue
        top = next((a for a in [el, *el.iterancestors()] if a.tag == T_P and a.getparent() is loc.secs[si]), None)
        if top is not None:
            ch.locpath = f"s{si}/p[{loc.secs[si].findall(T_P).index(top)}]"


def _walk(root: etree._Element, xpath: str):
    el = root
    for step in xpath.split("/")[1:]:
        idx = int(step[step.index("[") + 1 : -1])
        kids = list(el)
        if idx >= len(kids):
            return None
        el = kids[idx]
    return el


def check_scope(rep: DiffReport, allowed: list[str]) -> list[Change]:
    """허용 위치 목록 밖의 변경을 돌려준다. allowed 는 Locator 정규 경로(접두 일치)."""
    bad = []
    for c in rep.changes:
        if c.part == "Contents/content.hpf" or c.part.startswith("BinData/"):
            continue  # 이미지 추가에 따른 매니페스트 변경은 허용
        if (c.part.endswith("header.xml")
                and re.search(r"/(charProperties|paraProperties)\[\d+\](/(charPr|paraPr)\[\d+\])?$", c.xpath)
                and (c.what.startswith("속성 변경: itemCnt") or c.what.startswith("하위 요소 수") or c.what == "요소 추가")):
            continue  # 글자 크기 맞춤(fit)용 글자모양 추가: 기존 항목은 그대로, 끝에 추가만 허용
        if not c.locpath or not any(c.locpath == a or c.locpath.startswith(a + "/") for a in allowed):
            bad.append(c)
    return bad


def format_diff(rep: DiffReport, limit: int = 50) -> str:
    if rep.identical:
        s = "변경 없음: 모든 XML 노드·속성·텍스트가 원본과 동일"
        if rep.informational:
            s += "\n(참고) " + ", ".join(rep.informational)
        return s
    L = [f"변경 {len(rep.changes)}건, 추가 항목 {len(rep.added)}, 삭제 항목 {len(rep.removed)}"]
    L += [f"- 추가: {n}" for n in rep.added] + [f"- 삭제: {n}" for n in rep.removed]
    for c in rep.changes[:limit]:
        L.append(f"- [{c.part}] {c.locpath or c.xpath}: {c.what}")
    if len(rep.changes) > limit:
        L.append(f"- … 외 {len(rep.changes) - limit}건")
    return "\n".join(L)
