"""12차 관문 시험 (v0.9.3): 칸 폭 맞춤(fit) 순서 — 줄바꿈 우선, 자간 우선, 축소 하한, 축약 검토 표시.

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate12.py
개인 문서 없이 시험용 최소 HWPX 를 만들어 시험한다(글자 11pt, 줄 간격 160%).
"""
import os
import sys
import tempfile
import zipfile

from pehwpx.fill import Filler
from pehwpx.package import HwpxPackage
from pehwpx.verify import check_scope, check_structure, diff

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
HH = "http://www.hancom.co.kr/hwpml/2011/head"
OPF = "http://www.idpf.org/2007/opf/"

# (폭, 높이) HWPUNIT — 1pt = 100
CELLS = [
    (17300, 1500),  # 0: 낮은 칸(한 줄 높이), 하한(10pt)까지 축소 + 자간 필요
    (12000, 4200),  # 1: 폭은 좁지만 두 줄 들어가는 높이
    (12000, 1500),  # 2: 조금 넘치는 값(자간만으로 해결)
    (5000, 1500),   # 3: 매우 좁은 칸(하한까지 줄여도 불가)
]


def _cell(i: int, w: int, h: int) -> str:
    return (f'<hp:tc><hp:subList><hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t></hp:t></hp:run></hp:p>'
            f'</hp:subList><hp:cellAddr colAddr="{i}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{w}" height="{h}"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>')


def build(path: str) -> None:
    header = (f'<?xml version="1.0" encoding="UTF-8"?><hh:head xmlns:hh="{HH}"><hh:refList>'
              f'<hh:charProperties itemCnt="1"><hh:charPr id="0" height="1100"><hh:ratio hangul="100"/>'
              f'<hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/></hh:charPr>'
              f'</hh:charProperties><hh:paraProperties itemCnt="1"><hh:paraPr id="0">'
              f'<hh:lineSpacing type="PERCENT" value="160"/></hh:paraPr></hh:paraProperties></hh:refList></hh:head>')
    cells = "".join(_cell(i, w, h) for i, (w, h) in enumerate(CELLS))
    section = (f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">'
               f'<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:tbl rowCnt="1" colCnt="{len(CELLS)}">'
               f'<hp:tr>{cells}</hp:tr></hp:tbl></hp:run></hp:p></hs:sec>')
    hpf = (f'<?xml version="1.0" encoding="UTF-8"?><opf:package xmlns:opf="{OPF}"><opf:manifest>'
           f'<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
           f'<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
           f'</opf:manifest><opf:spine><opf:itemref idref="section0"/></opf:spine></opf:package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")
        z.writestr("version.xml", '<?xml version="1.0" encoding="UTF-8"?><v/>', zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/container.xml", '<?xml version="1.0" encoding="UTF-8"?><c/>', zipfile.ZIP_DEFLATED)
        z.writestr("Contents/content.hpf", hpf, zipfile.ZIP_DEFLATED)
        z.writestr("Contents/header.xml", header, zipfile.ZIP_DEFLATED)
        z.writestr("Contents/section0.xml", section, zipfile.ZIP_DEFLATED)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "mini.hwpx")
        build(src)
        pkg = HwpxPackage.open(src)
        f = Filler(pkg)
        long_v = "경기도 용인시 수지구 정보통신로 123"
        r0 = f.apply({"at": "s0/tbl[0]/r[0]/c[0]", "value": long_v, "fit": True})
        r1 = f.apply({"at": "s0/tbl[0]/r[0]/c[1]", "value": long_v, "fit": True})
        r2 = f.apply({"at": "s0/tbl[0]/r[0]/c[2]", "value": "정보통신기술사 이병일", "fit": True})
        r3 = f.apply({"at": "s0/tbl[0]/r[0]/c[3]", "value": long_v, "fit": True})
        f.finish()
        out = os.path.join(td, "o.hwpx")
        pkg.save(out)
        res = []
        for r in (r0, r1, r2, r3):
            res.append(r.kind)
        assert "줄(칸 높이 안)" in r1.kind, r1.kind            # 두 줄 높이 칸은 축소하지 않음
        assert "11pt 유지 자간" in r2.kind, r2.kind              # 조금 넘치면 크기 유지, 자간만
        assert "축약 검토" in r3.kind, r3.kind                  # 하한까지 줄여도 불가 → 원래 크기 + 표시
        for k in (r0.kind, r2.kind):
            for tok in k.replace(",", " ").split():
                if tok.endswith("pt"):
                    assert float(tok[:-2]) >= 10, k             # 하한 10pt(= max(10, 11×0.9)) 준수
        hdr = zipfile.ZipFile(out).read("Contents/header.xml").decode()
        assert 'height="9' not in hdr, "10pt 미만 글자모양이 생김"
        errs = check_structure(out)
        bad = check_scope(diff(src, out), sorted(f.allowed))
        assert not errs and not bad, (errs, bad)
        res.append("구조·범위 통과")
    for x in res:
        print("|", x, "|")
    print("\n결과: 관문 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
