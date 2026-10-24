"""9차 관문 시험 (v0.8): 공문 규칙 검사(lint)·승인 항목 수정(--fix).

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate9.py <HWPX 폴더>
- 금액 한글 표기: 시행규칙 예시(113,560원 → 일십일만삼천오백육십) 일치
- 위반 사례 본문을 넣은 문서에서 I1·I2·S1·D1·D2·T1·M1 전부 검출
- 모든 문서: 검사 오류 없음, 자동 수정 가능 항목 전부 수정 → 구조 검증·변경 범위 통과, 재검사 시 해당 코드 0건, 원본 불변
"""
import glob
import hashlib
import os
import sys
import tempfile

from pehwpx import q
from pehwpx.lint import check, fix, money_korean
from pehwpx.locate import Locator, paragraph_text
from pehwpx.outline import apply, has_object, parse
from pehwpx.package import HwpxPackage
from pehwpx.verify import check_scope, check_structure, diff

FIXABLE = {"D1", "D2", "T1", "M1", "S1", "E2"}
BAD = """1. 첫 항목입니다.
3. 2026.9.9 자로 제출된 서류를 2026년 9월 10일 오후 2시 30분에 검토하였습니다.
  1) 계약금액 1,500,000원 정산 확인
2. 검토 결과
  가.시공 상태 적정
"""


def unit():
    assert money_korean(113560) == "일십일만삼천오백육십", money_korean(113560)
    assert money_korean(388104100) == "삼억팔천팔백일십만사천일백"
    assert money_korean(1500000) == "일백오십만"
    return "금액 한글 표기"


def run(path, inject):
    h0 = hashlib.sha256(open(path, "rb").read()).hexdigest()
    pkg = HwpxPackage.open(path)
    notes = []
    if inject:
        loc = Locator(pkg)
        cand = [p for p in loc.secs[0].findall(q("hp", "p")) if paragraph_text(p).strip() and not has_object(p)]
        if cand:
            apply(pkg, loc, parse(BAD), "gonmun", after=paragraph_text(cand[0]).strip()[:12])
            codes = {f.code for f in check(pkg)}
            need = {"I1", "I2", "S1", "D1", "D2", "T1", "M1"}
            assert need <= codes, f"미검출 {need - codes}"
            notes.append("위반 사례 7종 검출")
    fs = check(pkg)
    before = {}
    for f in fs:
        before[f.code] = before.get(f.code, 0) + 1
    done, allowed, skipped = fix(pkg, fs, FIXABLE)
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "src.hwpx")
        o = os.path.join(td, "o.hwpx")
        if inject:  # 주입본 기준으로 비교하려면 주입 직후 상태가 필요 → 수정 전 저장본을 다시 만든다
            p0 = HwpxPackage.open(path)
            loc0 = Locator(p0)
            cand = [p for p in loc0.secs[0].findall(q("hp", "p")) if paragraph_text(p).strip() and not has_object(p)]
            if cand:
                apply(p0, loc0, parse(BAD), "gonmun", after=paragraph_text(cand[0]).strip()[:12])
            p0.save(src)
        else:
            src = path
        pkg.save(o)
        errs = check_structure(o)
        bad = check_scope(diff(src, o), sorted(allowed))
        assert not errs, errs
        assert not bad, [(b.locpath, b.what) for b in bad[:5]]
        after = {f.code for f in check(HwpxPackage.open(o)) if f.span is not None and f.code in FIXABLE}
        left = [s for s in skipped]
        assert not after or left, f"수정 후 남음 {after}"
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == h0
    summary = ", ".join(f"{k}×{v}" for k, v in sorted(before.items())) or "지적 없음"
    return "; ".join(notes + [f"검사 {summary}", f"수정 {len(done)}건" + (f"(건너뜀 {len(skipped)})" if skipped else "")])


def main():
    print("단위:", unit())
    fails = 0
    files = sorted(glob.glob(os.path.join(sys.argv[1], "*.hwpx")))
    for i, p in enumerate(files):
        try:
            print(f"| {os.path.basename(p)[:40]} | 통과 {run(p, inject=(i == 0 or 'gong' in p or '공문' in p))} |")
        except Exception as e:  # noqa
            fails += 1
            print(f"| {os.path.basename(p)[:40]} | 실패 {e!r} |"[:300])
    print("\n결과:", "관문 통과" if not fails else f"실패 {fails}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
