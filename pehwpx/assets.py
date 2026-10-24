"""도장·서명·체크 이미지 준비 (v0.9.2).

사용자가 종이에 쓴 서명·체크를 휴대폰으로 찍은 사진, 도장을 찍어 스캔한 이미지를 받아
(1) 배경을 투명하게, (2) 한 장에 여러 개를 쓴 경우 하나씩 나눠, (3) 여백을 잘라 PNG 로 저장하고,
(4) 역할 정의 파일 assets.json 을 만들거나 갱신한다. stamp 명령은 이 폴더를 --assets 로 쓴다.

  assets make <이미지…> --role seal|signature|check|name -o <폴더> [--max N]
  assets check <폴더>

개인 이미지는 스킬에 넣지 않는다. 결과 폴더는 사용자 PC(연결 폴더) 또는 대화 첨부로만 다룬다.
"""

from __future__ import annotations

import json
import os

ROLE_DEFAULTS = {
    "seal": {"width_mm": 15, "rotate_deg": 4, "jitter_mm": 0.5},
    "signature": {"width_mm": 24, "rotate_deg": 3, "jitter_mm": 0.8},
    "name": {"width_mm": 20, "rotate_deg": 2, "jitter_mm": 0.8},
    "check": {"width_mm": 6, "rotate_deg": 10, "jitter_mm": 1.2, "scale_pct": 10},
}
ROLE_KO = {"seal": "도장", "signature": "서명", "name": "성명", "check": "체크"}
MAX_SIDE = 2000  # 휴대폰 사진은 줄여서 처리(서명 폭 24mm 기준 충분한 해상도)


class AssetError(ValueError):
    pass


def _load(path: str):
    from PIL import Image, ImageOps
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGBA")  # 휴대폰 사진의 회전 정보 반영
    s = max(im.size)
    if s > MAX_SIDE:
        r = MAX_SIDE / s
        im = im.resize((max(1, int(im.size[0] * r)), max(1, int(im.size[1] * r))), Image.LANCZOS)
    return im


def transparent(im):
    """배경(테두리 색의 중앙값)을 투명하게. 이미 투명 영역이 있으면 그대로 둔다."""
    import numpy as np
    from PIL import Image
    a = np.asarray(im).astype(np.float32)
    if a[..., 3].min() < 200:
        return im
    border = np.concatenate([a[0, :, :3], a[-1, :, :3], a[:, 0, :3], a[:, -1, :3]])
    bg = np.median(border, axis=0)
    bd = np.sort(np.sqrt(((border - bg) ** 2).sum(1)))
    lo = min(70.0, max(35.0, float(bd[int(len(bd) * 0.90)]) + 12))
    hi = lo + 60
    d = np.sqrt(((a[..., :3] - bg) ** 2).sum(2))
    al = np.clip((d - lo) / (hi - lo), 0, 1) * 255
    out = a.copy()
    out[..., 3] = np.minimum(a[..., 3], al)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def split(im, gap_pct: float = 2.5, min_pct: float = 3.0) -> list:
    """투명 배경 이미지에서 떨어져 있는 글씨·인영 덩어리를 하나씩 잘라 돌려준다(위→아래, 왼→오른쪽).

    gap_pct: 이 거리(긴 변 대비 %) 안의 획은 한 덩어리로 본다(한 서명의 끊긴 획을 묶음).
    min_pct: 가장 큰 덩어리 면적 대비 이 % 미만은 잡티로 버린다.
    """
    import numpy as np
    try:
        from scipy import ndimage
    except ImportError:  # scipy 가 없으면 나누지 않고 한 장으로 둔다
        box = im.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
        return [im.crop(box)] if box else []
    m = np.asarray(im.getchannel("A")) > 128
    if not m.any():
        return []
    k = max(3, int(max(m.shape) * gap_pct / 100))
    grown = ndimage.binary_dilation(m, structure=np.ones((k, k), bool))
    lab, n = ndimage.label(grown)
    boxes = ndimage.find_objects(lab)
    areas = ndimage.sum(m, lab, range(1, n + 1))
    big = max(areas)
    items = []
    for i, sl in enumerate(boxes):
        if areas[i] < big * min_pct / 100:
            continue
        sub = m[sl] & (lab[sl] == i + 1)
        ys, xs = np.nonzero(sub)
        y0, y1 = sl[0].start + ys.min(), sl[0].start + ys.max() + 1
        x0, x1 = sl[1].start + xs.min(), sl[1].start + xs.max() + 1
        items.append((y0, x0, y1, x1, i + 1))
    # 같은 줄(세로로 겹침)끼리 묶어 왼쪽부터
    items.sort(key=lambda b: (b[0], b[1]))
    rows, cur = [], []
    for b in items:
        if cur and b[0] >= max(c[2] for c in cur):
            rows.append(cur)
            cur = []
        cur.append(b)
    if cur:
        rows.append(cur)
    out = []
    arr = np.asarray(im).copy()
    for row in rows:
        for y0, x0, y1, x1, li in sorted(row, key=lambda b: b[1]):
            piece = arr[y0:y1, x0:x1].copy()
            keep = lab[y0:y1, x0:x1] == li  # 이웃 덩어리 조각이 상자에 걸려도 지운다
            piece[..., 3] = np.where(keep, piece[..., 3], 0)
            from PIL import Image
            p = Image.fromarray(piece, "RGBA")
            pad = 2
            q = Image.new("RGBA", (p.size[0] + 2 * pad, p.size[1] + 2 * pad), (0, 0, 0, 0))
            q.paste(p, (pad, pad))
            out.append(q)
    return out


def make(images: list[str], role: str, out_dir: str, max_n: int | None = None) -> dict:
    if role not in ROLE_DEFAULTS:
        raise AssetError(f"역할은 {', '.join(ROLE_DEFAULTS)} 중 하나: {role}")
    os.makedirs(out_dir, exist_ok=True)
    pieces = []
    for path in images:
        im = transparent(_load(path))
        got = [im] if role == "seal" else split(im)  # 도장은 획이 떨어져 있어도 한 덩어리
        if role == "seal":
            box = im.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
            got = [im.crop(box)] if box else []
        pieces += [(path, p) for p in got]
    if not pieces:
        raise AssetError("이미지에서 글씨·인영을 찾지 못함(배경과 색 차이가 작거나 빈 이미지)")
    if max_n:
        pieces = pieces[:max_n]
    ko = ROLE_KO[role]
    cfg_path = os.path.join(out_dir, "assets.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    spec = cfg.get(role) or dict(ROLE_DEFAULTS[role], files=[])
    files = list(spec.get("files", []))
    n = len(files)
    saved = []
    for src, p in pieces:
        n += 1
        name = f"{ko}{n}.png"
        while os.path.exists(os.path.join(out_dir, name)):
            n += 1
            name = f"{ko}{n}.png"
        p.save(os.path.join(out_dir, name))
        files.append(name)
        saved.append((name, os.path.basename(src), p.size))
    spec["files"] = files
    cfg[role] = spec
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    return {"saved": saved, "assets": cfg_path, "role": role, "total": len(files)}


def check(folder: str) -> list[str]:
    """assets.json 과 이미지 파일 점검 결과(문제 목록, 비면 정상)."""
    from PIL import Image
    p = os.path.join(folder, "assets.json")
    if not os.path.exists(p):
        return [f"assets.json 없음: {folder}"]
    with open(p, encoding="utf-8") as fh:
        cfg = json.load(fh)
    bad = []
    for role, spec in cfg.items():
        files = spec.get("files") or ([spec["file"]] if "file" in spec else [])
        if not files:
            bad.append(f"{role}: files 비어 있음")
        for f in files:
            fp = os.path.join(folder, f)
            if not os.path.exists(fp):
                bad.append(f"{role}: 파일 없음 {f}")
                continue
            im = Image.open(fp)
            if im.mode != "RGBA" or im.getchannel("A").getextrema()[0] > 200:
                bad.append(f"{role}: {f} 배경이 투명하지 않음(배치 시 자동 처리되지만 assets make 로 미리 정리 권장)")
        if role == "signature" and len(files) < 2:
            bad.append("signature: 서명이 1개 — 2~3개를 두면 문서마다 다른 서명을 돌려 씀")
    return bad
