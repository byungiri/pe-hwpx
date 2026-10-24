"""5차 관문 시험 (v0.4.2): 서명란 자리(slot), '20  .   .   .' 날짜, 견본 안내 글자색 해제, 칸 폭 맞춤(fit), render-copy.

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate5.py <HWPX 폴더>
폴더 안에서 해당 형식(빈 날짜 '20  .', '(소속)', 회색 견본 글자, 좁은 칸)이 있는 문서만 시험한다.
"""
import glob
import os
import sys
import tempfile
import zipfile

from pehwpx.fill import Filler
from pehwpx.locate import Locator, cell_paragraphs, cells_of, paragraph_text
from pehwpx.package import HwpxPackage
from pehwpx.textforms import iter_dates
from pehwpx.verify import check_scope, check_structure, diff


def run(path: str) -> list[str]:
    out = []
    pkg = HwpxPackage.open(path)
    f = Filler(pkg)
    loc = f.loc
    texts = [paragraph_text(p) for sec in loc.secs for p in sec.iter("{*}p")]
    done = 0
    if any("(소속)" in t for t in texts):
        r = f.apply({"at": "contains:(소속)", "slot": "(소속)", "value": "기술법인 진성"})
        out.append(f"slot:{r.kind}")
        done += 1
    two = [t for t in texts if any(len(m["y"]) == 2 for m, _ in iter_dates(t))]
    if two:
        key = two[0].strip()[:6]
        r = f.apply({"at": "contains:" + key, "date": "2026-10-24"})
        assert "2026" in r.after, r
        out.append(f"date2:{r.before!r}->{r.after!r}")
        done += 1
    guide, narrow = None, None
    for si, ti, tbl in loc.tables():
        for c in cells_of(tbl):
            ps = cell_paragraphs(c.el)
            txt = "".join(paragraph_text(p) for p in ps).strip()
            first = next((r for p in ps for r in p.findall("{*}run")
                          if any((t.text or "").strip() for t in r.findall("{*}t"))), None)
            if not guide and first is not None and f._black_twin(first.get("charPrIDRef")):
                guide = loc.cell_path(tbl, c)
            w = c.el.find("{*}cellSz")
            if (not narrow and not txt and w is not None and 6000 < int(w.get("width")) < 9000
                    and len(ps) == 1 and len(ps[0].findall("{*}run")) == 1):
                narrow = loc.cell_path(tbl, c)
    if guide:
        r = f.apply({"at": guide, "value": "시험값"})
        assert "안내색 해제" in r.kind, r.kind
        out.append(f"guide:{guide}")
        done += 1
    if narrow:
        r = f.apply({"at": narrow, "value": "정보통신기술사정보통신", "fit": True})
        assert "pt" in r.kind or "줄바꿈" in r.kind, r.kind
        out.append(f"fit:{narrow}:{r.kind}")
        done += 1
    f.finish()
    if not done:
        return ["해당 없음"]
    with tempfile.TemporaryDirectory() as td:
        o = os.path.join(td, "o.hwpx")
        pkg.save(o)
        errs = check_structure(o)
        bad = check_scope(diff(path, o), sorted(f.allowed))
        assert not errs and not bad, (errs, bad)
        # render-copy
        from pehwpx.__main__ import cmd_render_copy

        class A:  # noqa
            file, output = o, os.path.join(td, "r.hwpx")
        cmd_render_copy(A)
        with zipfile.ZipFile(A.output) as z:
            st = z.read("settings.xml").decode("utf-8") if "settings.xml" in z.namelist() else ""
        assert 'name="PrintMethod" type="short">4<' not in st
    out.append("구조·범위 통과")
    return out


def main() -> int:
    folder = sys.argv[1]
    fails = 0
    for p in sorted(glob.glob(os.path.join(folder, "*.hwpx"))):
        try:
            r = run(p)
            print(f"| {os.path.basename(p)} | 통과 {'; '.join(r)} |")
        except Exception as e:  # noqa
            fails += 1
            print(f"| {os.path.basename(p)} | 실패 {e!r} |")
    print("\n결과:", "관문 통과" if not fails else f"실패 {fails}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
