"""4차 관문 시험(이미지 배치): 시험용 PNG 를 각 문서에 배치한 뒤 구조·변경 범위·재저장 보존성을 확인.

사용법: python tests/gate4.py <HWPX가 있는 폴더>
개인 도장·서명 대신 이 스크립트가 만든 단색 PNG 를 쓴다. 위치 정확도는 한글 렌더(PDF)로 별도 확인한다.
"""

import glob
import os
import struct
import sys
import tempfile
import zipfile
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pehwpx.image import ImageError, Stamper  # noqa: E402
from pehwpx.locate import T_P, Locator, paragraph_text  # noqa: E402
from pehwpx.package import HwpxPackage  # noqa: E402
from pehwpx.verify import check_scope, check_structure, diff  # noqa: E402


def make_png(path: str, w: int = 40, h: int = 40) -> None:
    raw = b"".join(b"\x00" + bytes([200, 30, 30, 255]) * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def check(src: str, png: str) -> tuple[bool, str]:
    pkg = HwpxPackage.open(src)
    loc = Locator(pkg)
    near = next((paragraph_text(p).strip()[:6] for sec in loc.secs for p in sec.iter(T_P)
                 if len(paragraph_text(p).strip()) >= 6), None)
    if not near:
        return True, "기준 문구 없음(건너뜀)"
    st = Stamper(pkg)
    try:
        st.stamp(png, near, 12)
    except ImageError as e:
        return False, f"배치 실패: {e}"
    out = os.path.join(tempfile.mkdtemp(), "st.hwpx")
    pkg.save(out)
    errs = check_structure(out)
    d = diff(src, out)
    outside = check_scope(d, sorted(st.allowed))
    # 결과물 재저장 보존성
    p2 = HwpxPackage.open(out)
    for n in p2.names():
        if n.endswith((".xml", ".hpf")):
            p2.touch(n)
    out2 = out + ".rt.hwpx"
    p2.save(out2)
    a, b = zipfile.ZipFile(out), zipfile.ZipFile(out2)
    same = all(a.read(n) == b.read(n) for n in a.namelist())
    bins = [n for n in d.added if n.startswith("BinData/")]
    ok = not errs and not outside and same and len(bins) == 1
    return ok, f"추가 그림 {len(bins)}, 구조오류 {len(errs)}, 범위 밖 {len(outside)}, 재저장 동일 {same}"


def roles_test() -> tuple[bool, str]:
    """역할 이미지 돌려쓰기·흔들림: 같은 역할을 연속 호출하면 파일이 차례로 바뀌고, 시드가 같으면 재현된다."""
    from pehwpx.image import Roles
    spec = {"check": {"files": ["a.png", "b.png", "c.png"], "width_mm": 6, "jitter_mm": 1.2, "rotate_deg": 10, "scale_pct": 10}}
    r1, r2 = Roles(spec, 7), Roles(spec, 7)
    seq1 = [r1.resolve("check") for _ in range(6)]
    seq2 = [r2.resolve("check") for _ in range(6)]
    files = [x["file"] for x in seq1]
    cyc = len(set(files[:3])) == 3 and files[:3] == files[3:]
    rep = seq1 == seq2
    bounded = all(abs(x["dx_mm"]) <= 1.2 and abs(x["dy_mm"]) <= 1.2 and abs(x["rotate_deg"]) <= 10
                  and 5.4 <= x["width_mm"] <= 6.6 for x in seq1)
    varied = len({round(x["dx_mm"], 3) for x in seq1}) > 1
    ok = cyc and rep and bounded and varied
    return ok, f"순환 {cyc}, 시드 재현 {rep}, 범위 내 {bounded}, 흔들림 {varied}"


def bg_test() -> tuple[bool, str]:
    """불투명 배경 이미지(회색 바탕 + 붉은 원)의 배경이 투명해지고 여백이 잘리는지."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return True, "Pillow 없음(건너뜀)"
    import io
    from pehwpx.image import prepare_image
    im = Image.new("RGB", (120, 120), (192, 192, 197))
    ImageDraw.Draw(im).ellipse((20, 20, 100, 100), outline=(170, 59, 66), width=8)
    p = os.path.join(tempfile.mkdtemp(), "seal.png")
    im.save(p)
    data, ext, grow = prepare_image(p, True, 0)
    out = Image.open(io.BytesIO(data)).convert("RGBA")
    corner_alpha = out.getpixel((0, 0))[3]
    ok = out.size[0] <= 84 and corner_alpha == 0 and ext == "png"
    return ok, f"잘린 크기 {out.size}, 모서리 투명도 {corner_alpha}"


def main(folder: str) -> int:
    png = os.path.join(tempfile.mkdtemp(), "test_stamp.png")
    make_png(png)
    fails = 0
    for name, fn in (("역할 이미지 돌려쓰기", roles_test), ("배경 투명화·여백 자르기", bg_test)):
        ok, msg = fn()
        fails += not ok
        print(f"- {name}: {'통과' if ok else '실패'} ({msg})")
    print()
    print("| 문서 | 결과 |")
    print("| --- | --- |")
    for fp in sorted(glob.glob(os.path.join(folder, "*.hwpx"))):
        ok, msg = check(fp, png)
        fails += not ok
        print(f"| {os.path.basename(fp)} | {'통과' if ok else '실패'} {msg} |")
    print(f"\n결과: {'관문 통과' if not fails else f'실패 {fails}건'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
