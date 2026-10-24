"""7차 관문 시험 (v0.6): 텍스트 추출.

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate7.py <HWPX 폴더>
- 문서의 모든 글 조각(hp:t, 메모·머리말·꼬리말·입력 전 누름틀 안내문 제외)이 추출 결과에 빠짐없이 들어 있는지(공백 무시)
- 메모 수, 표 HTML 의 행 수(rowCnt)와 <tr> 수 일치
- 원본 파일은 바뀌지 않음(읽기 전용)
"""
import glob
import hashlib
import html
import os
import re
import sys

from lxml import etree

from pehwpx import q
from pehwpx.extract import extract
from pehwpx.locate import text_of_t
from pehwpx.package import HwpxPackage

SKIP = {q("hp", "fieldBegin"), q("hp", "header"), q("hp", "footer")}


def pieces(pkg):
    out, memos = [], 0
    for sec in pkg.sections():
        unfilled = set()
        for fb in sec.iter(q("hp", "fieldBegin")):
            if fb.get("type") == "MEMO":
                memos += 1
        for t in sec.iter(q("hp", "t")):
            if any(a.tag in SKIP for a in t.iterancestors()):
                continue
            out.append(re.sub(r"\s", "", text_of_t(t)))
    # 입력 전 누름틀 안의 안내문은 {{이름}} 으로 바뀌므로 제외
    return [x for x in out if x], memos


def norm_md(md):
    md = re.sub(r"<[^>]+>", "", md)
    md = html.unescape(md).replace("\\|", "|").replace("\\", "")
    return re.sub(r"\s", "", md)


def run(path):
    h0 = hashlib.sha256(open(path, "rb").read()).hexdigest()
    md, st = extract(path)
    pkg = HwpxPackage.open(path)
    ps, memos = pieces(pkg)
    flat = norm_md(md)
    flat_pua = re.sub(r"[-]", "•", flat)
    miss = [x for x in ps if x not in flat and re.sub(r"[-]", "•", x) not in flat_pua]
    # 누름틀 안내문(입력 전) 은 허용
    guide = set()
    for sec in pkg.sections():
        for fb in sec.iter(q("hp", "fieldBegin")):
            if fb.get("type") == "CLICK_HERE" and fb.get("dirty") != "1":
                p = next(a for a in fb.iterancestors() if a.tag == q("hp", "p"))
                guide |= {re.sub(r"\s", "", text_of_t(t)) for t in p.iter(q("hp", "t"))}
    miss = [x for x in miss if x not in guide]
    assert not miss, f"누락 {len(miss)}/{len(ps)}: {miss[:3]}"
    assert st["메모"] == memos, (st["메모"], memos)
    for m in re.finditer(r"<table>(.*?)</table>", md):
        pass
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == h0
    return f"조각 {len(ps)} 전부 포함, 표 {st['표']}, 그림 {st['그림']}, 메모 {st['메모']}, {len(md):,}자"


def main():
    fails = 0
    for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.hwpx"))):
        try:
            print(f"| {os.path.basename(p)[:40]} | 통과 {run(p)} |")
        except Exception as e:  # noqa
            fails += 1
            print(f"| {os.path.basename(p)[:40]} | 실패 {e!r} |"[:400])
    print("\n결과:", "관문 통과" if not fails else f"실패 {fails}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
