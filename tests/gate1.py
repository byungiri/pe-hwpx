"""1단계 관문 시험: 보존성(왕복 무변경)과 변경 범위 검출.

사용법: python tests/gate1.py <HWPX가 있는 폴더>
- 시험 문서는 배포본에 포함하지 않는다. 사용자가 한글에서 직접 저장한 문서로 시험한다.
"""

import glob
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pehwpx.locate import Locator, T_T, cells_of  # noqa: E402
from pehwpx.package import HwpxPackage  # noqa: E402
from pehwpx.verify import check_scope, check_structure, diff  # noqa: E402


def roundtrip(src: str, reserialize: bool) -> tuple[bool, str]:
    pkg = HwpxPackage.open(src)
    if reserialize:
        for n in pkg.names():
            if n.endswith((".xml", ".hpf", ".rdf")):
                pkg.touch(n)
    out = os.path.join(tempfile.mkdtemp(), "rt.hwpx")
    pkg.save(out)
    a, b = zipfile.ZipFile(src), zipfile.ZipFile(out)
    same_bytes = a.namelist() == b.namelist() and all(a.read(n) == b.read(n) for n in a.namelist())
    errs = check_structure(out)
    rep = diff(src, out)
    ok = same_bytes and not errs and rep.identical
    return ok, f"바이트동일={same_bytes} 구조오류={len(errs)} 노드변경={len(rep.changes)}"


def scoped_edit(src: str) -> tuple[bool, str]:
    """첫 번째 비어 있지 않은 표 셀 하나만 고친 뒤, diff 가 그 셀만 지목하는지 확인."""
    pkg = HwpxPackage.open(src)
    loc = Locator(pkg)
    for si, ti, tbl in loc.tables():
        for c in cells_of(tbl):
            t = c.el.find(".//" + T_T)
            if t is not None and (t.text or "").strip():
                t.text = (t.text or "") + "★"
                pkg.touch(pkg.section_names()[si])
                out = os.path.join(tempfile.mkdtemp(), "ed.hwpx")
                pkg.save(out)
                path = loc.cell_path(tbl, c)
                rep = diff(src, out)
                outside = check_scope(rep, [path])
                ok = len(rep.changes) >= 1 and not outside and not check_structure(out)
                return ok, f"수정 셀 {path}, 검출 {len(rep.changes)}건, 범위 밖 {len(outside)}건"
    return True, "표 셀 없음(건너뜀)"


def fields_and_placeholders(src: str) -> tuple[bool, str]:
    """scan 이 찾은 누름틀·자리표시자를 locate 로 모두 다시 찾을 수 있는지 확인."""
    from pehwpx.scan import scan
    pkg = HwpxPackage.open(src)
    rep, loc = scan(pkg), Locator(pkg)
    specs = [f"field:{f['name']}" for f in rep["fields"]] + ["{{" + p["name"] + "}}" for p in rep["placeholders"]]
    if not specs:
        return True, "해당 없음"
    bad = []
    for sp in specs:
        try:
            loc.resolve(sp)
        except Exception:
            bad.append(sp)
    return not bad, f"{len(specs) - len(bad)}/{len(specs)} 위치 지정" + (f", 실패 {bad}" if bad else "")


def main(folder: str) -> int:
    files = sorted(glob.glob(os.path.join(folder, "*.hwpx")))
    if not files:
        print("HWPX 파일 없음")
        return 2
    fails = 0
    print("| 문서 | 왕복(원본 유지) | 왕복(강제 재직렬화) | 단일 셀 수정 검출 | 누름틀·자리표시자 |")
    print("| --- | --- | --- | --- | --- |")
    for f in files:
        cols = []
        for fn in (lambda: roundtrip(f, False), lambda: roundtrip(f, True), lambda: scoped_edit(f),
                   lambda: fields_and_placeholders(f)):
            ok, msg = fn()
            fails += not ok
            cols.append(("통과 " if ok else "실패 ") + msg)
        print(f"| {os.path.basename(f)} | " + " | ".join(cols) + " |")
    print(f"\n결과: {'관문 통과' if not fails else f'실패 {fails}건'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
