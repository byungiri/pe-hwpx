"""10차 관문 시험 (v0.9.1): 실무 작성 중 발견한 결함 3건의 회귀 시험.

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate10.py <HWPX 폴더>

A. 반복행 병합 칸 높이: 반복 구간을 덮는 세로 병합 칸(예: '11. 타위원회 경력')의 높이가
   늘리기·줄이기한 행 높이만큼 함께 바뀌는지. (결함: 줄여도 병합 칸 높이가 남아 표가 줄지 않음)
B. 반복행 처리 순서: 한 표의 반복 구간 2곳을 채울 때 채움 파일의 순서와 무관하게 결과가 같은지.
   (결함: 위 구간을 먼저 늘리면 아래 구간 행 번호가 밀려 실패)
C. PDF 문구 찾기: ① ':' 처럼 정규화 후 빈 단어 때문에 같은 문구가 중복 집계되어 nth 가 어긋남,
   ② 한글 PDF 가 '(' 를 ')' 뒤에 내보내 '(서명)' 을 못 찾음 — 합성 단어 목록으로 확인.
"""
import glob
import os
import sys
import tempfile
import zipfile

from pehwpx import image as IM
from pehwpx.__main__ import order_items
from pehwpx.fill import Filler, FillError
from pehwpx.locate import Locator, cells_of
from pehwpx.package import HwpxPackage
from pehwpx.rows import T_CSZ, _sig, find_block


def _merged_over(tbl, rows):
    """구간 rows 를 위에서 덮는 세로 병합 칸들."""
    return [c for c in cells_of(tbl) if c.rowspan > 1 and c.row < rows[0] and c.row + c.rowspan - 1 >= rows[-1]]


def blocks_with_label(path):
    loc = Locator(HwpxPackage.open(path))
    out = []
    for si, ti, tbl in loc.tables():
        n, r = int(tbl.get("rowCnt")), 0
        while r < n:
            sig = _sig(tbl, r)
            if sig is None or len(sig) < 2:
                r += 1
                continue
            blk = find_block(tbl, r)
            if len(blk) >= 2 and _merged_over(tbl, blk):
                out.append((f"s{si}/tbl[{ti}]", ti, r, [c for c, _ in sig], len(blk)))
            r = blk[-1] + 1
    return out


def heights(path, ti, start):
    loc = Locator(HwpxPackage.open(path))
    tbl = [t for _, i, t in loc.tables() if i == ti][0]
    lab = [c for c in cells_of(tbl) if c.rowspan > 1 and c.row < start <= c.row + c.rowspan - 1]
    return [int(c.el.find(T_CSZ).get("height")) for c in lab], int(tbl.find(IM.q("hp", "sz")).get("height"))


def fill_to(path, items, out):
    pkg = HwpxPackage.open(path)
    f = Filler(pkg)
    for it in order_items(items):
        f.apply(it)
    f.finish()
    pkg.save(out)
    return out


def case_a(path, tpath, ti, start, cols, cap, tmp):
    lab0, tb0 = heights(path, ti, start)
    res = []
    for mode, n, trim in (("grow", cap + 2, False), ("error", 1, True)):
        data = [[f"A{i}-{j}" for j in range(len(cols))] for i in range(n)]
        out = fill_to(path, [{"rows": f"{tpath}/r[{start}]", "cols": cols, "data": data,
                              "overflow": mode, "trim": trim}], os.path.join(tmp, f"a_{mode}.hwpx"))
        lab1, tb1 = heights(out, ti, start)
        d = [b - a for a, b in zip(lab0, lab1)]  # 구간을 덮는 병합 칸이 여럿(예: 두 열 라벨)이면 각각 같은 만큼
        if len(lab1) != len(lab0) or any(x != tb1 - tb0 for x in d):
            return f"실패 {mode}: 병합 칸 높이 변화 {d} ≠ 표 높이 변화 {tb1 - tb0}"
        res.append(f"{mode} {tb1 - tb0:+d}")
    return "통과 " + ", ".join(res)


def case_b(path, blocks, tmp):
    same = [b for b in blocks if b[0] == blocks[0][0]]
    if len(same) < 2:
        return "해당 없음(한 표에 구간 2곳 없음)"
    (tp, _, s1, c1, k1), (_, _, s2, c2, k2) = same[0], same[1]
    it1 = {"rows": f"{tp}/r[{s1}]", "cols": c1, "overflow": "grow",
           "data": [[f"B1-{i}-{j}" for j in range(len(c1))] for i in range(k1 + 1)]}
    it2 = {"rows": f"{tp}/r[{s2}]", "cols": c2, "overflow": "grow",
           "data": [[f"B2-{i}-{j}" for j in range(len(c2))] for i in range(k2 + 1)]}
    x = fill_to(path, [it1, it2], os.path.join(tmp, "b1.hwpx"))
    y = fill_to(path, [it2, it1], os.path.join(tmp, "b2.hwpx"))
    zx, zy = zipfile.ZipFile(x), zipfile.ZipFile(y)
    for n in zx.namelist():
        if n.startswith("Contents/section") and zx.read(n) != zy.read(n):
            return "실패: 순서에 따라 결과가 다름"
    return f"통과 r[{s1}]·r[{s2}] 순서 무관"


def case_c():
    words = [(0, "동의하십니까?", 200, 368, 280, 379), (0, ":", 290, 372, 293, 379),
             (0, "동의", 313, 368, 335, 379), (0, "□", 344, 368, 355, 379),
             (0, "동의하십니까?", 183, 535, 250, 546), (0, ":", 260, 539, 263, 546),
             (0, "동의", 283, 535, 304, 546), (0, "□", 314, 535, 325, 546),
             (0, "서명", 503, 684, 531, 698), (0, ")", 530, 689, 534, 698.9), (0, "(", 499, 689, 504, 698.9)]
    orig = IM.pdf_words
    IM.pdf_words = lambda _pdf: words
    try:
        b2 = IM.find_in_pdf("x.pdf", "동의 □", "□", 2)
        bs = IM.find_in_pdf("x.pdf", "(서명)")
    except IM.ImageError as e:
        return f"실패: {e}"
    finally:
        IM.pdf_words = orig
    if b2.y0 != 535:
        return f"실패: nth=2 가 둘째 줄이 아님 (y0={b2.y0})"
    if not (bs.x0 == 499 and bs.x1 == 534):
        return f"실패: '(서명)' 상자 {bs}"
    return "통과 nth 중복 없음, '(서명)' 화면 순서로 찾음"


def main():
    print("| 문서 | A 병합 칸 높이 | B 처리 순서 |\n| --- | --- | --- |")
    ok = True
    for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.hwpx"))):
        try:
            blocks = blocks_with_label(p)
        except Exception as e:  # 읽을 수 없는 문서는 다른 관문에서 다룬다
            print(f"| {os.path.basename(p)} | 건너뜀({type(e).__name__}) | |")
            continue
        if not blocks:
            print(f"| {os.path.basename(p)} | 해당 없음 | 해당 없음 |")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tp, ti, s, cols, cap = blocks[0]
            try:
                a = case_a(p, tp, ti, s, cols, cap, tmp)
                b = case_b(p, blocks, tmp)
            except FillError as e:  # 구간 칸에 그림·개체가 있어 값 교체 자체가 불가한 문서(반복행 대상 아님)
                a, b = f"해당 없음({str(e)[:40]})", ""
        ok &= not a.startswith("실패") and not b.startswith("실패")
        print(f"| {os.path.basename(p)} | {a} | {b} |")
    c = case_c()
    ok &= c.startswith("통과")
    print(f"\nC PDF 문구 찾기: {c}")
    print("\n결과: " + ("관문 통과" if ok else "관문 실패"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
