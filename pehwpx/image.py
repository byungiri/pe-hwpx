"""이미지 배치: 직인·서명·체크 표시를 문서 위 지정 위치에 겹쳐 넣는다 (설계서 4.6).

두 가지 위치 결정 방식
1) 측정 방식(권장): 한글로 변환한 PDF 에서 기준 글자('(인', '□' 등)의 실제 좌표를 읽어
   쪽(용지) 기준 절대 좌표로 배치한다. 오차가 거의 없다.
2) 추정 방식: PDF 가 없을 때 문단 정렬·글자 크기로 글자 위치를 계산해 문단 기준으로 배치한다.
   한 줄 문단에서 수 mm 이내 오차를 목표로 하며, 결과는 반드시 화면으로 확인한다.

그림 XML 구성은 한글이 저장한 실제 문서의 hp:pic 구조(OWPML)를 따른다.
"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import unicodedata
import zipfile
from dataclasses import dataclass

from lxml import etree

from . import NS, q
from .locate import T_P, T_RUN, T_T, LocateError, Locator, norm, paragraph_text
from .package import HwpxPackage

HWPUNIT_PER_PT = 100          # 1pt = 100 HWPUNIT
HWPUNIT_PER_MM = 7200 / 25.4  # 1inch = 7200 HWPUNIT
PX_UNIT = 75                  # 96dpi 기준 1px = 75 HWPUNIT (한글 저장값과 일치)
UINT32 = 1 << 32


class ImageError(ValueError):
    pass


# ================================================================ 이미지 정보
def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":  # JPEG: SOF 마커 탐색
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise ImageError("PNG/JPEG 만 지원")


def media_type(path: str) -> tuple[str, str]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return "png", "image/png"
    if ext in (".jpg", ".jpeg"):
        return "jpg", "image/jpeg"
    raise ImageError(f"지원하지 않는 이미지 형식: {ext}")


def prepare_image(path: str, remove_bg: bool = True, rotate_deg: float = 0.0,
                  trim: bool = True) -> tuple[bytes, str, float]:
    """이미지를 읽어 필요 시 (1) 불투명 배경을 투명하게, (2) 회전한 PNG 바이트를 돌려준다.

    배경 제거: 테두리 픽셀의 중앙값을 배경색으로 보고, 배경색과의 색 차이로 투명도를 정한다.
    (회색 종이 위 붉은 인영, 흰 종이 위 검은 서명 모두 해당) Pillow 가 없으면 원본을 그대로 쓴다.
    """
    with open(path, "rb") as f:
        data = f.read()
    try:
        from PIL import Image
    except ImportError:
        return data, os.path.splitext(path)[1].lower().lstrip(".").replace("jpeg", "jpg"), 1.0
    import io
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    w0 = im.size[0]
    changed = False
    if remove_bg:
        alpha = im.getchannel("A")
        if alpha.getextrema()[0] > 200:  # 투명 영역이 없는 사진형 이미지
            im = _remove_background(im)
            changed = True
    if trim:  # 투명 여백을 잘라 '지정 폭 = 인영·서명 자체의 폭' 이 되게 한다
        box = im.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
        if box and box != (0, 0) + im.size:
            pad = 1
            box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.size[0], box[2] + pad), min(im.size[1], box[3] + pad))
            im = im.crop(box)
            w0 = im.size[0]
            changed = True
    if rotate_deg:
        im = im.rotate(rotate_deg, resample=Image.BICUBIC, expand=True)
        changed = True
    if not changed:
        return data, os.path.splitext(path)[1].lower().lstrip(".").replace("jpeg", "jpg"), 1.0
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), "png", im.size[0] / w0  # 회전으로 늘어난 폭 비율


def _remove_background(im):
    w, h = im.size
    px = im.load()
    border = [px[x, y][:3] for x in range(w) for y in (0, h - 1)] + [px[x, y][:3] for y in range(h) for x in (0, w - 1)]
    bg = tuple(sorted(c[i] for c in border)[len(border) // 2] for i in range(3))
    # 배경 명암이 고르지 않은 사진 대비: 테두리 색 차이의 최댓값보다 크게 투명 경계를 잡는다
    bd = sorted(((c[0] - bg[0]) ** 2 + (c[1] - bg[1]) ** 2 + (c[2] - bg[2]) ** 2) ** 0.5 for c in border)
    # (인영이 테두리에 닿는 이미지도 있어 상위 10% 는 제외하고, 상한 70 으로 잉크가 흐려지지 않게 한다)
    lo = min(70, max(35, bd[int(len(bd) * 0.90)] + 12))
    hi = lo + 60  # lo 이하 완전 투명, hi 이상 불투명
    out = im.copy()
    op = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            d = ((r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2) ** 0.5
            al = 0 if d <= lo else (255 if d >= hi else int((d - lo) / (hi - lo) * 255))
            op[x, y] = (r, g, b, min(a, al))
    return out


def add_image(pkg: HwpxPackage, path: str, remove_bg: bool = True, rotate_deg: float = 0.0) -> tuple[str, int, int, float]:
    data, ext, grow = prepare_image(path, remove_bg, rotate_deg)
    mt = "image/png" if ext == "png" else "image/jpeg"
    used = {it.get("id") for it in pkg.manifest_items()}
    n = 1
    while f"image{n}" in used or pkg.has(f"BinData/image{n}.{ext}"):
        n += 1
    bid = f"image{n}"
    pkg.add_binary(f"{bid}.{ext}", data, mt, bid)
    w, h = png_size(data)
    return bid, w, h, grow


# ================================================================ 그림 요소
def _u32(v: int) -> str:
    """음수 좌표는 한글 저장 방식대로 32비트 부호 없는 값으로 기록."""
    return str(v % UINT32)


def build_pic(bid: str, px_w: int, px_h: int, w: int, h: int, x: int, y: int,
              rel: str, comment: str, uid: int) -> etree._Element:
    ow, oh = px_w * PX_UNIT, px_h * PX_UNIT
    sx, sy = w / ow, h / oh
    hp, hc = NS["hp"], NS["hc"]
    xml = (
        f'<hp:pic xmlns:hp="{hp}" xmlns:hc="{hc}" id="{uid}" zOrder="{50 + uid % 1000}" numberingType="PICTURE" '
        f'textWrap="IN_FRONT_OF_TEXT" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" '
        f'instid="{uid // 2}" reverse="0">'
        f'<hp:offset x="0" y="0"/><hp:orgSz width="{ow}" height="{oh}"/><hp:curSz width="{w}" height="{h}"/>'
        f'<hp:flip horizontal="0" vertical="0"/>'
        f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>'
        f'<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        f'<hc:scaMatrix e1="{sx:.6f}" e2="0" e3="0" e4="0" e5="{sy:.6f}" e6="0"/>'
        f'<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
        f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{ow}" y="0"/><hc:pt2 x="{ow}" y="{oh}"/><hc:pt3 x="0" y="{oh}"/></hp:imgRect>'
        f'<hp:imgClip left="0" right="{ow}" top="0" bottom="{oh}"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:imgDim dimwidth="{ow}" dimheight="{oh}"/>'
        f'<hc:img binaryItemIDRef="{bid}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/><hp:effects/>'
        f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="0" affectLSpacing="0" flowWithText="{0 if rel == "PAPER" else 1}" allowOverlap="1" '
        f'holdAnchorAndSO="0" vertRelTo="{rel}" horzRelTo="{rel}" vertAlign="TOP" horzAlign="LEFT" '
        f'vertOffset="{_u32(y)}" horzOffset="{_u32(x)}"/>'
        f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:shapeComment/></hp:pic>'
    )
    el = etree.fromstring(xml)
    el.find(q("hp", "shapeComment")).text = comment
    return el


def _attach(p: etree._Element, pic: etree._Element) -> None:
    """문단의 첫 런 맨 앞에 그림을 넣는다. 새 글자·새 줄을 만들지 않아 쪽 흐름이 바뀌지 않는다."""
    runs = p.findall(T_RUN)
    if runs:
        runs[0].insert(0, pic)
        return
    run = etree.Element(T_RUN)
    run.set("charPrIDRef", "0")
    run.append(pic)
    lsa = p.find(q("hp", "linesegarray"))
    if lsa is not None:
        lsa.addprevious(run)
    else:
        p.append(run)


# ================================================================ 측정 방식 (PDF)
@dataclass
class Box:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


def pdf_words(pdf: str) -> list[tuple[int, str, float, float, float, float]]:
    try:
        xml = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise ImageError(f"pdftotext 실행 실패(poppler 필요): {e}")
    root = etree.fromstring(xml, etree.XMLParser(recover=True))
    out = []
    for pi, page in enumerate(root.iter("{*}page")):
        for w in page.iter("{*}word"):
            out.append((pi, w.text or "", float(w.get("xMin")), float(w.get("yMin")),
                        float(w.get("xMax")), float(w.get("yMax"))))
    return out


def pdf_page_size(pdf: str) -> tuple[float, float]:
    try:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, check=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise ImageError(f"pdfinfo 실행 실패(poppler 필요): {e}")
    m = re.search(r"Page size:\s*([\d.]+) x ([\d.]+)", out)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def doc_page_size(pkg: HwpxPackage) -> tuple[float, float]:
    """첫 구역의 용지 크기(pt). landscape 속성과 무관하게 width/height 값 기준."""
    for sec in pkg.sections():
        pp = next(sec.iter(q("hp", "pagePr")), None)
        if pp is not None:
            return int(pp.get("width")) / HWPUNIT_PER_PT, int(pp.get("height")) / HWPUNIT_PER_PT
    return 0.0, 0.0


def cell_box_in_pdf(pdf: str, box: "Box", dpi: int = 150) -> tuple[float, float, float, float]:
    """기준 문구를 둘러싼 표 칸의 테두리(pt)를 PDF 그림에서 찾는다. 문구 바깥 여백 열·행을 따라 짙은 선까지 탐색."""
    import tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        stem = os.path.join(td, "pg")
        subprocess.run(["pdftoppm", "-f", str(box.page + 1), "-l", str(box.page + 1), "-r", str(dpi),
                        "-gray", "-png", pdf, stem], check=True, capture_output=True)
        f = next(os.path.join(td, n) for n in os.listdir(td) if n.endswith(".png"))
        im = Image.open(f).convert("L")
    px, (W, H) = im.load(), im.size
    k = dpi / 72.0
    cx, cy = (box.x0 + box.x1) / 2 * k, (box.y0 + box.y1) / 2 * k
    gap = 2 * k  # 문구 바로 바깥(2pt) 세로 열에서 위·아래 테두리 탐색

    def dark(x, y):
        return 0 <= x < W and 0 <= y < H and px[int(x), int(y)] < 110

    def scan(x, y, dx, dy, limit):
        for i in range(1, int(limit)):
            if dark(x + dx * i, y + dy * i):
                return (x + dx * i, y + dy * i)
        raise ImageError("칸 테두리를 찾지 못함")

    left = scan(box.x0 * k - 1, cy, -1, 0, 120 * k)[0]
    right = scan(box.x1 * k + 1, cy, 1, 0, 120 * k)[0]
    col = box.x0 * k - gap
    top = scan(col, cy, 0, -1, 200 * k)[1]
    bottom = scan(col, cy, 0, 1, 200 * k)[1]
    return left / k, top / k, right / k, bottom / k


def _reading_order(words: list) -> list:
    """PDF 단어를 쪽 → 줄(첫 단어 세로 범위 안) → 왼쪽부터 순서로 다시 놓는다.
    한글 PDF 는 '(서명)' 의 '(' 를 ')' 뒤에 내보내는 등 글자 출력 순서가 화면 순서와 다를 때가 있다."""
    out = []
    for pg in sorted({w[0] for w in words}):
        ws = sorted((w for w in words if w[0] == pg), key=lambda w: (w[3] + w[5]) / 2)
        line, lines, band = [], [], None
        for w in ws:
            c = (w[3] + w[5]) / 2
            if band is not None and not (band[0] <= c <= band[1]):
                lines.append(line)
                line = []
            line.append(w)
            if len(line) == 1:
                band = (w[3], w[5])  # 줄 첫 단어의 세로 범위 안에 중심이 들면 같은 줄(괄호·문장부호는 기준선이 낮음)
        if line:
            lines.append(line)
        for ln in lines:
            out.extend(sorted(ln, key=lambda w: w[2]))
    return out


def find_in_pdf(pdf: str, near: str, on: str | None = None, nth: int = 1) -> Box:
    """near 문구(띄어쓰기 무시)를 찾아 그 영역(또는 그 안의 on 단어) 상자를 돌려준다."""
    words = _reading_order(pdf_words(pdf))
    want = norm(near)
    hits = []
    for i in range(len(words)):
        if not norm(words[i][1]):  # ':' 등 정규화 후 빈 단어에서 시작하면 같은 문구가 중복 집계되어 nth 가 어긋난다
            continue
        acc = ""
        for j in range(i, min(i + 30, len(words))):
            if words[j][0] != words[i][0]:
                break
            acc += norm(words[j][1])
            if not want.startswith(acc):
                break
            if acc == want:
                hits.append(words[i:j + 1])
                break
    if len(hits) < nth:
        raise ImageError(f"PDF 에서 '{near}' 를 찾지 못함 (발견 {len(hits)}건)")
    seq = hits[nth - 1]
    if on:
        seq = [w for w in seq if norm(on) in norm(w[1])] or seq
    return Box(seq[0][0], min(w[2] for w in seq), min(w[3] for w in seq),
               max(w[4] for w in seq), max(w[5] for w in seq))


# ================================================================ 추정 방식
def _char_em(ch: str) -> float:
    if ch == " ":
        return 0.5
    if unicodedata.east_asian_width(ch) in ("W", "F") or ch in "□■☐☑○●":
        return 1.0
    if ch in ".,:;'!|":
        return 0.33
    return 0.55


def _header_info(pkg: HwpxPackage):
    h = pkg.xml("Contents/header.xml").getroot()
    heights = {c.get("id"): int(c.get("height", "1000")) for c in h.iter(q("hh", "charPr"))}
    aligns = {}
    for pp in h.iter(q("hh", "paraPr")):
        al = pp.find(".//" + q("hh", "align"))
        aligns[pp.get("id")] = al.get("horizontal") if al is not None else "LEFT"
    return heights, aligns


def _avail_width(p: etree._Element) -> int | None:
    """문단의 줄 폭. 채움으로 줄 배치 정보가 지워졌으면 같은 영역의 다른 문단 값을 쓴다."""
    def seg_w(x):
        lsa = x.find(q("hp", "linesegarray"))
        seg = lsa.find(q("hp", "lineseg")) if lsa is not None else None
        return int(seg.get("horzsize")) if seg is not None else None
    w = seg_w(p)
    if w:
        return w
    parent = p.getparent()
    if parent is not None:
        for sib in parent.findall(T_P):
            w = seg_w(sib)
            if w and sib.get("paraPrIDRef") == p.get("paraPrIDRef"):
                return w
        for sib in parent.findall(T_P):
            w = seg_w(sib)
            if w:
                return w
    return None


def estimate_in_paragraph(pkg: HwpxPackage, p: etree._Element, near: str, on: str | None,
                          avail: int | None) -> tuple[int, int, int]:
    """(x 중심, y 중심, 줄 높이) — 문단 기준 HWPUNIT."""
    heights, aligns = _header_info(pkg)
    chars = []
    for run in p.findall(T_RUN):
        hgt = heights.get(run.get("charPrIDRef"), 1000)
        for t in run.findall(T_T):
            for ch in (t.text or ""):
                chars.append((ch, hgt))
    text = "".join(c for c, _ in chars)
    target = (on or near)
    pos = text.find(target)
    if pos < 0:
        compact = re.sub(r"\s", "", target)
        m = re.search(r"\s*".join(map(re.escape, compact)), text)
        if not m:
            raise ImageError(f"문단에서 '{target}' 를 찾지 못함")
        pos, end = m.start(), m.end()
    else:
        end = pos + len(target)
    adv = [_char_em(c) * hgt for c, hgt in chars]
    total = sum(adv)
    if avail is None:
        avail = _avail_width(p) or int(total)
    align = aligns.get(p.get("paraPrIDRef"), "LEFT")
    start = (avail - total) / 2 if align == "CENTER" else (avail - total if align == "RIGHT" else 0)
    x0 = start + sum(adv[:pos])
    x1 = start + sum(adv[:end])
    line_h = max((hgt for _, hgt in chars), default=1000)
    return int((x0 + x1) / 2), int(line_h * 0.55), line_h


def _lines(p):
    lsa = p.find(q("hp", "linesegarray"))
    return [] if lsa is None else lsa.findall(q("hp", "lineseg"))


def _para_height(p, heights) -> int:
    segs = _lines(p)
    if segs:
        first, last = segs[0], segs[-1]
        return int(last.get("vertpos")) + int(last.get("vertsize")) + int(last.get("spacing", "0")) - int(first.get("vertpos"))
    hs = [heights.get(r.get("charPrIDRef"), 1000) for r in p.findall(T_RUN)] or [1000]
    return int(max(hs) * 1.6)  # 줄 간격 160% 가정


def vertical_anchor(pkg: HwpxPackage, p: etree._Element, need: int = 0) -> tuple[etree._Element, int]:
    """(앵커 문단, 앵커 문단 위쪽부터 대상 문단 위쪽까지 거리).

    한글은 문단 기준 개체의 음수 세로 위치를 0 으로 제한하므로, 바로 위 문단(줄 배치 정보가 있는)에
    앵커하고 아래로 내려 배치한다. 위 문단이 없으면 대상 문단 자체(거리 0).
    """
    heights, _ = _header_info(pkg)
    parent = p.getparent()
    sibs = parent.findall(T_P) if parent is not None else [p]
    i = sibs.index(p)
    best = (p, 0)
    for j in range(i - 1, -1, -1):
        if _lines(sibs[j]):
            dist = sum(_para_height(sibs[k], heights) for k in range(j, i))
            best = (sibs[j], dist)
            if dist >= need:  # 그림 위쪽이 앵커 문단 아래에 오도록 충분히 위 문단까지 올라간다
                return best
    return best


# ================================================================ 역할 이미지 (돌려쓰기·손 느낌)
class Roles:
    """assets.json 의 역할(@seal 등)을 해석한다.

    역할 정의 예:
      "seal":  {"files": ["a.png", "b.png"], "width_mm": 14, "rotate_deg": 6}
      "check": {"files": ["c1.png", "c2.png", "c3.png"], "width_mm": 10,
                "jitter_mm": 1.2, "rotate_deg": 10, "scale_pct": 10}
    - files 는 한 문서 안에서 차례로 돌려 쓴다(시작 순번은 문서마다 무작위).
    - jitter_mm: 가로·세로 ± 무작위 이동, rotate_deg: ± 무작위 회전, scale_pct: 크기 ± 무작위 변화.
    """

    def __init__(self, roles: dict, seed: int):
        import random
        self.roles = roles
        self.rng = random.Random(seed)
        self.seed = seed
        self.count: dict[str, int] = {}
        self.start: dict[str, int] = {}

    def resolve(self, role: str, jitter_mm: float | None = None, rotate_max_deg: float | None = None) -> dict:
        """jitter_mm·rotate_max_deg 를 주면 그 항목만 역할 기본값 대신 그 범위로 흔든다(예: 작은 상자 체크는 0.3mm)."""
        if role not in self.roles:
            raise ImageError(f"assets.json 에 '{role}' 역할 없음 (가능: {', '.join(self.roles) or '없음'})")
        spec = self.roles[role]
        if isinstance(spec, str):
            spec = {"file": spec}
        files = spec.get("files") or [spec["file"]]
        if role not in self.start:
            self.start[role] = self.rng.randrange(len(files))
        i = self.count.get(role, 0)
        self.count[role] = i + 1
        f = files[(self.start[role] + i) % len(files)]
        j, r, sc = float(spec.get("jitter_mm", 0)), float(spec.get("rotate_deg", 0)), float(spec.get("scale_pct", 0))
        if jitter_mm is not None:
            j = float(jitter_mm)
        if rotate_max_deg is not None:
            r = float(rotate_max_deg)
        u = self.rng.uniform
        return {
            "file": f,
            "width_mm": float(spec.get("width_mm", 15)) * (1 + u(-sc, sc) / 100),
            "dx_mm": u(-j, j), "dy_mm": u(-j, j),
            "rotate_deg": u(-r, r),
            "remove_bg": bool(spec.get("remove_bg", True)),
        }


# ================================================================ 배치 진입점
@dataclass
class Placed:
    image: str
    near: str
    mode: str
    where: str
    x_mm: float
    y_mm: float
    w_mm: float


class Stamper:
    def __init__(self, pkg: HwpxPackage):
        self.pkg = pkg
        self.loc = Locator(pkg)
        self.placed: list[Placed] = []
        self.allowed: set[str] = set()
        self._uid = 1_500_000_000

    def _next_uid(self) -> int:
        self._uid += 7
        return self._uid

    def _anchor_paragraph(self, near: str, nth: int = 1) -> tuple[int, etree._Element]:
        want = norm(near)
        hits = [(si, p) for si, sec in enumerate(self.loc.secs) for p in sec.iter(T_P)
                if want and want in norm(paragraph_text(p))]
        if len(hits) < nth:
            raise ImageError(f"문서에서 '{near}' 가 든 문단을 찾지 못함")
        return hits[nth - 1]

    def stamp(self, image: str, near: str, width_mm: float, on: str | None = None, nth: int = 1,
              pdf: str | None = None, dx_mm: float = 0, dy_mm: float = 0,
              rotate_deg: float = 0.0, remove_bg: bool = True, fit_cell: bool = False,
              margin_mm: float = 1.0) -> Placed:
        if not os.path.exists(image):
            raise ImageError(f"이미지 없음: {image}")
        si, p = self._anchor_paragraph(near, nth)
        bid, pw, ph, grow = add_image(self.pkg, image, remove_bg, rotate_deg)
        w = int(width_mm * grow * HWPUNIT_PER_MM)  # 회전 시 늘어난 테두리만큼 키워 인영 크기 유지
        h = int(w * ph / pw)
        dx, dy = int(dx_mm * HWPUNIT_PER_MM), int(dy_mm * HWPUNIT_PER_MM)
        name = os.path.basename(image)
        if pdf:
            pw_pt, ph_pt = pdf_page_size(pdf)
            dw, dh = doc_page_size(self.pkg)
            if dw and pw_pt and (abs(pw_pt - dw) > 3 or abs(ph_pt - dh) > 3):
                raise ImageError(f"PDF 쪽 크기({pw_pt:.0f}x{ph_pt:.0f}pt)가 문서 용지({dw:.0f}x{dh:.0f}pt)와 다름 — "
                                 "모아찍기 등 인쇄 설정 때문일 수 있음. render-copy 로 만든 사본을 PDF 로 변환해 사용")
            box = find_in_pdf(pdf, near, on, nth)
            # 용지 기준 좌표는 앵커 문단이 놓인 쪽에 적용되므로 기준 문구가 든 문단을 앵커로 쓰면 쪽 번호와 무관
            cx = (box.x0 + box.x1) / 2 * HWPUNIT_PER_PT
            cy = (box.y0 + box.y1) / 2 * HWPUNIT_PER_PT
            if fit_cell:  # 사진처럼 칸 안에 꽉 차게: 칸 테두리 실측 → 여백 남기고 비율 유지 최대 크기, 칸 중앙
                l, t, r_, b = cell_box_in_pdf(pdf, box)
                m = margin_mm * HWPUNIT_PER_MM
                cw, ch = (r_ - l) * HWPUNIT_PER_PT - 2 * m, (b - t) * HWPUNIT_PER_PT - 2 * m
                w = int(min(cw, ch * pw / ph))
                h = int(w * ph / pw)
                width_mm = w / HWPUNIT_PER_MM
                cx, cy = (l + r_) / 2 * HWPUNIT_PER_PT, (t + b) / 2 * HWPUNIT_PER_PT
            # 용지 기준 절대 좌표. 앵커는 기준 문구가 든 문단(같은 쪽)
            pic = build_pic(bid, pw, ph, w, h, int(cx - w / 2) + dx, int(cy - h / 2) + dy, "PAPER",
                            f"pe-hwpx 배치: {name}", self._next_uid())
            _attach(p, pic)
            where, mode = self.loc.where(p), f"측정(PDF {box.page + 1}쪽)"
            xmm, ymm = (cx - w / 2 + dx) / HWPUNIT_PER_MM, (cy - h / 2 + dy) / HWPUNIT_PER_MM
        else:
            cx, cy, _lh = estimate_in_paragraph(self.pkg, p, near, on, None)
            anchor, dist = vertical_anchor(self.pkg, p, need=h // 2 - cy - dy)
            y = dist + cy - h // 2 + dy
            note = ""
            if y < 0:
                y, note = 0, ", 위쪽 공간 부족으로 세로 위치 제한"
            pic = build_pic(bid, pw, ph, w, h, cx - w // 2 + dx, y, "PARA",
                            f"pe-hwpx 배치: {name}", self._next_uid())
            _attach(anchor, pic)
            where, mode = self.loc.where(anchor), "추정(문단 기준" + note + ")"
            cy = y + h // 2 - dist
            xmm, ymm = (cx - w / 2 + dx) / HWPUNIT_PER_MM, (cy - h / 2 + dy) / HWPUNIT_PER_MM
        self.allowed.add(where)
        self._touch(si)
        res = Placed(name + (f" ({rotate_deg:+.1f}°)" if rotate_deg else ""), near, mode, where,
                     round(xmm, 1), round(ymm, 1), round(width_mm, 1))
        self.placed.append(res)
        return res

    def _touch(self, si: int) -> None:
        self.pkg.touch(self.pkg.section_names()[si])
