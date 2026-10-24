"""11차 관문 시험 (v0.9.2): 이미지 준비(assets make·check) — 합성 사진으로 시험(개인 이미지 불필요).

사용: PYTHONPATH=<스킬 폴더> python3 tests/gate11.py
- 회색 종이 사진에 서명 3개(각각 끊긴 획 포함)·체크 3개를 그린 뒤 역할별로 나눠지는지,
  배경이 투명해지는지, assets.json 이 만들어지고 누적되는지, check 가 정상인지 확인.
"""
import json
import math
import os
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

from pehwpx import assets as A


def photo(path, kind):
    im = Image.new("RGB", (2400, 900), (232, 228, 220))
    d = ImageDraw.Draw(im)
    for i in range(3):
        x0, y0 = 200 + i * 750, 400
        if kind == "signature":
            d.line([(x0 + j * 40, y0 + int(80 * math.sin(j / 2 + i))) for j in range(12)], fill=(20, 20, 60), width=9)
            d.line([(x0 + 120, y0 - 60), (x0 + 180, y0 + 90)], fill=(20, 20, 60), width=9)
        else:
            d.line([(x0, y0), (x0 + 40, y0 + 60), (x0 + 140, y0 - 90)], fill=(10, 10, 10), width=10)
    im.filter(ImageFilter.GaussianBlur(0.8)).save(path, quality=90)


def main():
    ok = True
    with tempfile.TemporaryDirectory() as t:
        out = os.path.join(t, "도장")
        for kind in ("signature", "check"):
            p = os.path.join(t, kind + ".jpg")
            photo(p, kind)
            r = A.make([p], kind, out)
            n = len(r["saved"])
            good = n == 3
            for name, _, _ in r["saved"]:
                a = Image.open(os.path.join(out, name)).getchannel("A")
                good &= a.getextrema()[0] == 0 and a.getextrema()[1] > 200  # 투명 배경 + 불투명 획
            print(f"| {kind} | {n}개 | {'통과' if good else '실패'} |")
            ok &= good
        cfg = json.load(open(os.path.join(out, "assets.json"), encoding="utf-8"))
        acc = set(cfg) == {"signature", "check"} and len(cfg["signature"]["files"]) == 3
        print(f"| assets.json 누적 | {sorted(cfg)} | {'통과' if acc else '실패'} |")
        bad = A.check(out)
        print(f"| assets check | {bad or '이상 없음'} | {'통과' if not bad else '실패'} |")
        ok &= acc and not bad
    print("\n결과: " + ("관문 통과" if ok else "관문 실패"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
