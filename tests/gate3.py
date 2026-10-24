"""3차 관문 시험(양식맵): 등록 초안의 자기 일치, 내장 양식맵의 오인 방지, 양식맵 작성 결과 검증.

사용법: python tests/gate3.py <HWPX가 있는 폴더>
"""

import glob
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pehwpx import formmap  # noqa: E402
from pehwpx.fill import Filler, FillError  # noqa: E402
from pehwpx.package import HwpxPackage  # noqa: E402
from pehwpx.verify import check_scope, check_structure, diff  # noqa: E402


def check(src: str) -> tuple[bool, str]:
    pkg = HwpxPackage.open(src)
    m = formmap.register(pkg, "t", "t")
    if not m["fields"]:
        return True, "등록 항목 없음(건너뜀)"
    sc = formmap.score(pkg, m)
    self_ok = sc["score"] >= formmap.MATCH_THRESHOLD and not sc["fields_missing"]
    # 이름=값 작성: 항목마다 하나씩 (같은 칸을 두 번 채우지 않도록 위치 중복 제외)
    values, seen = {}, set()
    for name, fd in m["fields"].items():
        if fd["at"] in seen:
            continue
        seen.add(fd["at"])
        values[name] = "2026-10-24" if fd.get("date") else "양식맵시험"
    items, missing = formmap.build_items(m, values, None)
    f = Filler(HwpxPackage.open(src))
    rejected = 0
    for it in items:
        try:
            f.apply(it)
        except FillError:
            rejected += 1
    f.finish()
    out = os.path.join(tempfile.mkdtemp(), "made.hwpx")
    f.pkg.save(out)
    outside = check_scope(diff(src, out), sorted(f.allowed))
    errs = check_structure(out)
    ok = self_ok and not missing and not outside and not errs
    return ok, (f"항목 {len(m['fields'])}, 자기일치 {sc['score']:.2f}, 작성 {len(f.applied)}(거부 {rejected}), "
                f"범위 밖 {len(outside)}, 구조오류 {len(errs)}")


def builtin_false_positive(files: list[str]) -> list[str]:
    """내장 양식맵이 다른 종류 문서에 잘못 일치하는지 확인 (일치한 문서 목록 반환)."""
    hits = []
    for fp in files:
        top = formmap.best_match(HwpxPackage.open(fp))
        if top and top[0]["score"] >= formmap.MATCH_THRESHOLD:
            hits.append(f"{os.path.basename(fp)}→{top[0]['map'].get('title')}")
    return hits


def main(folder: str) -> int:
    files = sorted(glob.glob(os.path.join(folder, "*.hwpx")))
    fails = 0
    print("| 문서 | 결과 |")
    print("| --- | --- |")
    for fp in files:
        ok, msg = check(fp)
        fails += not ok
        print(f"| {os.path.basename(fp)} | {'통과' if ok else '실패'} {msg} |")
    print("\n내장 양식맵 일치 문서: " + (", ".join(builtin_false_positive(files)) or "없음"))
    print(f"\n결과: {'관문 통과' if not fails else f'실패 {fails}건'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
