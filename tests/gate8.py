"""8차 관문 시험 (v0.7): 개조식 본문 작성(write).

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate8.py <HWPX 폴더>
- 입력 해석: 수준·종류(항목/참고/본문), 수준 건너뛰기 보정
- 공문 기호 순서: 1. 가. 1) 가) (1) (가) ① ㉮, 하위 번호 초기화
- 문서별: 본문(구역) 삽입, 표 칸 교체 → 구조 검증·변경 범위 통과, 내어쓰기 값(left = 시작 + 기호폭, intent = -기호폭),
  추출 결과에 기호와 글이 순서대로 나타남, 원본 파일 불변
"""
import glob
import hashlib
import os
import re
import sys
import tempfile

from pehwpx import q
from pehwpx.extract import extract
from pehwpx.locate import Locator, cell_paragraphs, cells_of, paragraph_text
from pehwpx.outline import apply, gonmun_mark, has_object, parse
from pehwpx.package import HwpxPackage
from pehwpx.verify import check_scope, check_structure, diff

BODY = """- 첫째 항목입니다. 줄이 넘어갈 만큼 충분히 긴 문장을 넣어 내어쓰기가 적용되는지 확인하기 위한 시험 문장입니다.
  - 둘째 수준 항목
    - 셋째 수준 항목
      - 넷째 수준 항목
  이어지는 본문 문단
- 둘째 항목
※ 참고 문구
"""


def unit():
    it = parse(BODY)
    assert [x["level"] for x in it] == [0, 1, 2, 3, 3, 0, 0], [x["level"] for x in it]
    assert [x["kind"] for x in it] == ["item"] * 4 + ["body", "item", "note"]
    assert parse("    - 바로 깊은 수준")[0]["level"] == 0  # 건너뛰기 보정
    assert [gonmun_mark(k, 1) for k in range(8)] == ["1.", "가.", "1)", "가)", "(1)", "(가)", "①", "㉮"]
    assert gonmun_mark(1, 3) == "다."
    return "해석·기호 순서"


def check_hang(pkg, paras):
    h = pkg.xml(next(n for n in pkg.names() if n.endswith("header.xml"))).getroot()
    pps = {e.get("id"): e for e in h.iter(q("hh", "paraPr"))}
    for p in paras:
        mg = next(pps[p.get("paraPrIDRef")].iter(q("hh", "margin")))
        left = int(mg.find(q("hc", "left")).get("value"))
        intent = int(mg.find(q("hc", "intent")).get("value"))
        txt = paragraph_text(p)
        if re.match(r"^(□|○|-|·|※|\d+\.|[가-하]\.|\d+\)|[가-하]\)|\(\d+\)|\([가-하]\)|[①-⑮]|[㉮-㉻]) ", txt):
            assert intent < 0 and left >= 0, (txt[:10], left, intent)
            for mg2 in pps[p.get("paraPrIDRef")].iter(q("hh", "margin")):
                if mg2.getparent().tag.endswith("default"):
                    assert int(mg2.find(q("hc", "intent")).get("value")) == 2 * intent


def run(path):
    h0 = hashlib.sha256(open(path, "rb").read()).hexdigest()
    out = []
    items = parse(BODY)
    for mode in ("section", "cell"):
        pkg = HwpxPackage.open(path)
        loc = Locator(pkg)
        if mode == "section":
            sec = loc.secs[0]
            cand = [p for p in sec.findall(q("hp", "p")) if paragraph_text(p).strip() and not has_object(p)]
            if not cand:
                continue
            anchor = paragraph_text(cand[0]).strip()[:12]
            r = apply(pkg, loc, items, "gonmun", after=anchor, end=True)
        else:
            cell = None
            for si, ti, tbl in loc.tables():
                for c in cells_of(tbl):
                    ps = cell_paragraphs(c.el)
                    if ps and not any(has_object(p) for p in ps) and any(paragraph_text(p).strip() for p in ps):
                        cell = loc.cell_path(tbl, c)
                        break
                if cell:
                    break
            if not cell:
                continue
            r = apply(pkg, loc, items, "report", at=cell)
        with tempfile.TemporaryDirectory() as td:
            o = os.path.join(td, "o.hwpx")
            pkg.save(o)
            errs = check_structure(o)
            bad = check_scope(diff(path, o), sorted(r["allowed"]))
            assert not errs, errs
            assert not bad, [(b.locpath, b.what) for b in bad[:5]]
            md, _ = extract(o)
            flat = re.sub(r"\s", "", re.sub(r"<[^>]+>", "", md))
            seq = (["1.첫째", "가.둘째", "1)셋째", "가)넷째", "이어지는", "2.둘째항목", "※참고"] if mode == "section"
                   else ["□첫째", "○둘째", "-셋째", "·넷째", "이어지는", "□둘째항목", "※참고"])
            pos = -1
            for s in seq:
                k = flat.find(s, pos + 1)
                assert k > pos, (mode, s)
                pos = k
            if mode == "section":
                assert "끝." in flat[pos:pos + 40]
            p2 = HwpxPackage.open(o)
            keys = ("첫째 항목", "수준 항목", "둘째 항목", "참고 문구")
            paras = [p for sec in p2.sections() for p in sec.iter(q("hp", "p"))
                     if any(k in paragraph_text(p) for k in keys)]
            assert len(paras) == 6, len(paras)
            check_hang(p2, paras)
        out.append(f"{mode} +{r['inserted']}문단")
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == h0
    return "; ".join(out) or "해당 없음"


def main():
    print("단위:", unit())
    fails = 0
    for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.hwpx"))):
        try:
            print(f"| {os.path.basename(p)[:40]} | 통과 {run(p)} |")
        except Exception as e:  # noqa
            fails += 1
            print(f"| {os.path.basename(p)[:40]} | 실패 {e!r} |"[:300])
    print("\n결과:", "관문 통과" if not fails else f"실패 {fails}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
