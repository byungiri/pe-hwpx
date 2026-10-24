"""6차 관문 시험 (v0.5): 반복행 — 늘리기(grow)·별지(annex)·줄이기(trim)·초과 거부(error).

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate6.py <HWPX 폴더>
각 문서에서 같은 열 구성이 2행 이상 이어지는 첫 반복 구간을 찾아 시험한다(없으면 '해당 없음').
"""
import glob
import os
import sys
import tempfile

from pehwpx.fill import Filler, FillError
from pehwpx.locate import Locator, cell_paragraphs, cells_of, paragraph_text
from pehwpx.package import HwpxPackage
from pehwpx.rows import _sig, find_block
from pehwpx.verify import check_scope, check_structure, diff


def first_block(path):
    loc = Locator(HwpxPackage.open(path))
    for si, ti, tbl in loc.tables():
        n = int(tbl.get("rowCnt"))
        for r in range(n):
            sig = _sig(tbl, r)
            if sig is None or len(sig) < 2:
                continue
            blk = find_block(tbl, r)
            if len(blk) >= 2:
                return f"s{si}/tbl[{ti}]", r, [c for c, _ in sig], len(blk)
    return None


def run_case(path, tpath, start, cols, cap, n, mode, trim=False):
    pkg = HwpxPackage.open(path)
    f = Filler(pkg)
    data = [[f"시험{i}-{j}" for j in range(len(cols))] for i in range(n)]
    item = {"rows": f"{tpath}/r[{start}]", "cols": cols, "data": data, "overflow": mode, "trim": trim}
    try:
        f.apply(item)
    except FillError as e:
        return "거부", str(e)
    f.finish()
    with tempfile.TemporaryDirectory() as td:
        o = os.path.join(td, "o.hwpx")
        pkg.save(o)
        errs = check_structure(o)
        bad = check_scope(diff(path, o), sorted(f.allowed))
        assert not errs, errs
        assert not bad, [(b.locpath, b.what) for b in bad[:5]]
        loc = Locator(HwpxPackage.open(o))
        tbl = loc.resolve(tpath).el
        blk = find_block(tbl, start)
        texts = [paragraph_text(cell_paragraphs(next(c for c in cells_of(tbl) if c.row == r and c.col == cols[0]).el)[0])
                 for r in blk]
        rowsum = len(tbl.findall("{*}tr"))
        assert rowsum == int(tbl.get("rowCnt")), (rowsum, tbl.get("rowCnt"))
        return len(blk), texts


def run(path):
    fb = first_block(path)
    if not fb:
        return ["해당 없음"]
    tpath, start, cols, cap = fb
    out = [f"{tpath}/r[{start}] 구간 {cap}행"]
    k, texts = run_case(path, tpath, start, cols, cap, cap + 2, "grow")
    assert k == cap + 2 and texts[-1] == f"시험{cap + 1}-0", (k, texts)
    out.append(f"grow {cap}→{k}")
    k, texts = run_case(path, tpath, start, cols, cap, cap + 2, "annex")
    assert k == cap and texts[-1] == "별지 참조", (k, texts)
    out.append("annex")
    k, msg = run_case(path, tpath, start, cols, cap, cap + 1, "error")
    assert k == "거부", k
    out.append("error 거부")
    if cap >= 3:
        k, texts = run_case(path, tpath, start, cols, cap, 1, "error", trim=True)
        assert k == 1 or k >= 1, k
        out.append(f"trim {cap}→{k}")
    return out


def main():
    fails = 0
    for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.hwpx"))):
        try:
            print(f"| {os.path.basename(p)} | 통과 {'; '.join(run(p))} |")
        except Exception as e:  # noqa
            fails += 1
            print(f"| {os.path.basename(p)} | 실패 {e!r} |")
    print("\n결과:", "관문 통과" if not fails else f"실패 {fails}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
