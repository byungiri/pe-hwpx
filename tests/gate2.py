"""2단계 관문 시험: 채움 후 구조 무결성, 지정 위치 밖 변경 0건, 채운 값 재판독.

사용법: python tests/gate2.py <HWPX가 있는 폴더>
각 문서에서 scan 이 찾은 후보(라벨 칸, 문단 항목, 날짜, 누름틀, 자리표시자)를 시험값으로 채운다.
"""

import glob
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pehwpx.fill import Filler, FillError  # noqa: E402
from pehwpx.locate import Locator, cell_text, field_value, paragraph_text, cell_paragraphs  # noqa: E402
from pehwpx.package import HwpxPackage  # noqa: E402
from pehwpx.scan import scan  # noqa: E402
from pehwpx.verify import check_scope, check_structure, diff  # noqa: E402

V = "시험값가나다"


def plan(rep: dict) -> list[dict]:
    items, used = [], set()
    for c in rep["candidates"][:3]:
        items.append({"at": c["spec"], "value": V}); used.add(c["path"])
    for it in rep.get("items", []):
        key = (it["where"], it["kind"], it["label"])
        if key in used or it["where"] in used:
            continue
        used.add(key)
        if it["kind"] == "항목":
            items.append({"at": it["where"], "after": it["label"], "value": V})
        elif it["kind"] == "선택":
            items.append(dict(it["entry"]))
        else:
            items.append({"at": it["where"], "date": "2026-10-24"})
    items += [{"at": f"field:{f['name']}", "value": V} for f in rep["fields"]]
    items += [{"at": "{{" + p["name"] + "}}", "value": V} for p in rep["placeholders"]]
    return items


def check_file(src: str) -> tuple[bool, str]:
    rep = scan(HwpxPackage.open(src))
    items = plan(rep)
    if not items:
        return True, "채움 후보 없음(건너뜀)"
    pkg = HwpxPackage.open(src)
    f = Filler(pkg)
    skipped = 0
    for it in items:
        try:
            f.apply(it)
        except FillError:
            skipped += 1  # 탭 포함 문단 등 지원 범위 밖 — 저장 전 거부되는 것이 정상
    f.finish()
    out = os.path.join(tempfile.mkdtemp(), "filled.hwpx")
    pkg.save(out)
    errs = check_structure(out)
    d = diff(src, out)
    outside = check_scope(d, sorted(f.allowed))
    # 재판독: 채운 값이 실제로 읽히는지
    loc = Locator(HwpxPackage.open(out))
    unread = 0
    for a in f.applied:
        t = loc.resolve(a.where) if a.where else None
        if a.kind.startswith("체크"):
            ok = "■" in a.after
        elif a.kind == "누름틀":
            ok = field_value(loc.resolve(a.spec).el)[0] == V
        elif t is None:
            ok = False
        else:
            text = cell_text(t.el) if t.kind == "cell" else paragraph_text(t.el)
            ok = a.after in text
        unread += not ok
    ok = not errs and not outside and unread == 0
    return ok, f"채움 {len(f.applied)}건(거부 {skipped}), 구조오류 {len(errs)}, 범위 밖 {len(outside)}, 재판독 실패 {unread}"


def main(folder: str) -> int:
    files = sorted(glob.glob(os.path.join(folder, "*.hwpx")))
    fails = 0
    print("| 문서 | 결과 |")
    print("| --- | --- |")
    for fp in files:
        ok, msg = check_file(fp)
        fails += not ok
        print(f"| {os.path.basename(fp)} | {'통과' if ok else '실패'} {msg} |")
    print(f"\n결과: {'관문 통과' if not fails else f'실패 {fails}건'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
