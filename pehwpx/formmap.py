"""양식맵: 자주 쓰는 양식의 입력 항목을 이름으로 등록해 두고 이름=값으로 작성한다 (설계서 5.2).

양식맵(JSON) 구조 — 개인정보(현재 값)는 담지 않는다.
{
  "form_id": "employment-certificate",
  "title": "재직증명서",
  "match": {"labels": ["소속", "직위", ...], "phrases": ["재직증명서"]},
  "fields": {
    "용도":   {"at": "item:용도", "required": true, "desc": "제출처·용도"},
    "발급일": {"at": "contains:상기와 같이", "date": true, "default": "today"},
    "직위":   {"at": "label:직위", "from": "person.title"}
  }
}
필드 키: at(위치) · date(날짜 숫자만 교체) · after(문단 항목 라벨) · required · default · from(자료 JSON 경로) · desc
"""

from __future__ import annotations

import glob
import json
import os
import re

from .fill import has_date
from .textforms import BOX_OFF, find_item, iter_dates
from .locate import LocateError, Locator, T_P, T_TC, cell_paragraphs, norm, paragraph_text
from .package import HwpxPackage
from .scan import scan

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms")


class MapError(ValueError):
    pass


# ================================================================ 등록(초안 생성)
def _anchor_for_cell(loc: Locator, where: str) -> str:
    """셀 경로 대신 양식 개정에 강한 'contains:문구' 앵커를 찾는다."""
    try:
        tgt = loc.resolve(where)
    except LocateError:
        return where
    if tgt.kind != "cell":
        return where
    for p in cell_paragraphs(tgt.el):
        txt = paragraph_text(p).strip()
        if len(norm(txt)) < 4 or has_date(txt) or re.search(r"[:：]", txt):
            continue
        phrase = re.sub(r"\s+", " ", txt)[:16].strip()
        try:
            t2 = loc.resolve("contains:" + phrase)
        except LocateError:
            continue
        if t2.kind == "cell" and t2.el is tgt.el:
            return "contains:" + phrase
    return where


def register(pkg: HwpxPackage, form_id: str = "", title: str = "") -> dict:
    rep = scan(pkg)
    loc = Locator(pkg)
    fields: dict[str, dict] = {}

    def add(name: str, spec: dict) -> None:
        base, n = name, 2
        while name in fields:
            name = f"{base}{n}"
            n += 1
        fields[name] = spec

    value_cells = set()
    for c in rep["candidates"]:
        value_cells.add(c["path"])
        add(norm(c["label"]), {"at": c["spec"], "desc": "표 칸"})
    item_count: dict[str, int] = {}
    date_n = 0
    for it in rep.get("items", []):
        if it["where"] in value_cells and it["kind"] == "날짜":
            continue  # 생년월일·입사일 등 이미 표 칸으로 등록된 날짜
        if it["kind"] == "선택":
            add(it["label"], {"at": it["entry"]["at"], "check": it["label"], "desc": "체크 상자 (값: 예)"})
            continue
        if it["kind"] == "항목":
            lab = it["label"]
            item_count[lab] = item_count.get(lab, 0) + 1
            spec = f"item:{lab}" + (f"#{item_count[lab]}" if item_count[lab] > 1 else "")
            add(lab, {"at": spec, "desc": "문단 항목"})
        else:
            date_n += 1
            add("날짜" if date_n == 1 else f"날짜{date_n}",
                {"at": _anchor_for_cell(loc, it["where"]), "date": True, "default": "today", "desc": "날짜 (숫자만 교체)"})
    for f in rep["fields"]:
        add(f["name"], {"at": f"field:{f['name']}", "desc": "누름틀"})
    for p in rep["placeholders"]:
        add(p["name"], {"at": "{{" + p["name"] + "}}", "desc": "자리표시자"})

    phrases = []
    for sec in loc.secs:
        for p in sec.iter(T_P):
            t = norm(paragraph_text(p))
            if 3 <= len(t) <= 20:
                phrases.append(t)
                break
    return {
        "form_id": form_id or "form",
        "title": title or (phrases[0] if phrases else "양식"),
        "match": {"labels": sorted({norm(c["label"]) for c in rep["candidates"]}), "phrases": phrases[:1]},
        "fields": fields,
    }


# ================================================================ 대조
def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if path.endswith((".yaml", ".yml")):
        import yaml
        m = yaml.safe_load(txt)
    else:
        m = json.loads(txt)
    if not isinstance(m, dict) or "fields" not in m:
        raise MapError(f"양식맵 형식 오류: {path}")
    m["_path"] = path
    return m


def map_paths(extra_dirs: list[str] | None = None) -> list[str]:
    dirs = [BUILTIN_DIR] + list(extra_dirs or [])
    if os.environ.get("PEHWPX_FORMS"):
        dirs += os.environ["PEHWPX_FORMS"].split(os.pathsep)
    out = []
    for d in dirs:
        for ext in ("*.json", "*.yaml", "*.yml"):
            out += sorted(glob.glob(os.path.join(d, ext)))
    return out


def score(pkg: HwpxPackage, m: dict) -> dict:
    loc = Locator(pkg)
    ok, bad = [], []
    for name, fd in m["fields"].items():
        try:
            loc.resolve(fd["at"])
            ok.append(name)
        except LocateError:
            bad.append(name)
    all_cells = "".join(norm(paragraph_text(p)) for sec in loc.secs for p in sec.iter(T_P))
    labels = m.get("match", {}).get("labels", [])
    phrases = m.get("match", {}).get("phrases", [])
    lab_hit = sum(1 for l in labels if l in all_cells)
    ph_hit = sum(1 for p in phrases if p in all_cells)
    f_ratio = len(ok) / max(len(m["fields"]), 1)
    l_ratio = lab_hit / len(labels) if labels else 1.0
    p_ratio = ph_hit / len(phrases) if phrases else 1.0
    total = 0.6 * f_ratio + 0.3 * l_ratio + 0.1 * p_ratio
    return {"map": m, "score": round(total, 3), "fields_ok": ok, "fields_missing": bad,
            "labels": f"{lab_hit}/{len(labels)}", "phrases": f"{ph_hit}/{len(phrases)}"}


def best_match(pkg: HwpxPackage, extra_dirs: list[str] | None = None) -> list[dict]:
    res = []
    for p in map_paths(extra_dirs):
        try:
            res.append(score(pkg, load(p)))
        except Exception as e:  # 손상된 양식맵은 건너뛴다
            res.append({"map": {"_path": p, "title": "(읽기 실패)", "fields": {}}, "score": 0.0,
                        "fields_ok": [], "fields_missing": [], "labels": str(e), "phrases": ""})
    return sorted(res, key=lambda r: -r["score"])


MATCH_THRESHOLD = 0.9


# ================================================================ 작성
def build_items(m: dict, values: dict[str, str], data: dict | None) -> tuple[list[dict], list[str]]:
    """양식맵 + 이름=값 → 채움 항목. 반환: (항목, 누락된 필수 항목)."""
    unknown = [k for k in values if k not in m["fields"]]
    if unknown:
        raise MapError(f"양식맵에 없는 항목: {', '.join(unknown)} (가능: {', '.join(m['fields'])})")
    items, missing = [], []
    for name, fd in m["fields"].items():
        if name in values:
            v = values[name]
        elif fd.get("from") and data is not None and _dig(data, fd["from"]) is not None:
            v = _dig(data, fd["from"])
        elif "default" in fd:
            v = fd["default"]
        else:
            if fd.get("required"):
                missing.append(name)
            continue
        it = {"at": fd["at"]}
        if fd.get("check"):
            if str(v).strip() in ("", "아니오", "no", "false", "0"):
                continue
            it["check"] = fd["check"]
            items.append(it)
            continue
        if fd.get("date"):
            it["date"] = str(v)
        else:
            it["value"] = str(v)
            if fd.get("after"):
                it["after"] = fd["after"]
        items.append(it)
    return items, missing


def _dig(data: dict, path: str):
    cur = data
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def describe(m: dict) -> str:
    L = [f"양식맵: {m.get('title')} ({m.get('form_id')})", "",
         "| 항목 | 위치 | 방식 | 필수 | 기본값·자료 | 설명 |", "| --- | --- | --- | --- | --- | --- |"]
    for name, fd in m["fields"].items():
        how = "체크" if fd.get("check") else "날짜" if fd.get("date") else ("문단 항목" if fd["at"].startswith("item:") or fd.get("after") else "교체")
        src = fd.get("default", "") or (f"from {fd['from']}" if fd.get("from") else "")
        L.append(f"| {name} | `{fd['at']}` | {how} | {'예' if fd.get('required') else ''} | {src} | {fd.get('desc', '')} |")
    return "\n".join(L)
