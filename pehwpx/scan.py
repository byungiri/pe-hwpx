"""양식 분석: 문서 구조와 채움 후보 위치를 목록화한다 (설계서 4.1)."""

from __future__ import annotations

import re
from collections import Counter

from . import q
from .fill import has_date
from .textforms import BOX_OFF, find_item, iter_dates
from .locate import Locator, T_P, T_TC, T_TBL, cells_of, field_value, norm, paragraph_text
from .package import HwpxPackage

_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_LABEL_MAX = 14


def _short(s: str, n: int = 30) -> str:
    s = s.replace("\n", " ⏎ ").replace("\t", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _is_label(text: str) -> bool:
    t = norm(text)
    if not (1 <= len(t) <= _LABEL_MAX):
        return False
    if re.fullmatch(r"[\d.,\-~()/%년월일]+", t):  # 숫자·날짜만 있는 셀은 라벨 아님
        return False
    return True


def scan(pkg: HwpxPackage) -> dict:
    loc = Locator(pkg)
    rep: dict = {"file": pkg.path, "sections": [], "tables": [], "candidates": [],
                 "fields": [], "placeholders": [], "pictures": [], "binaries": []}

    for si, sec in enumerate(loc.secs):
        ps = sec.findall(T_P)
        rep["sections"].append({"index": si, "paragraphs": len(ps),
                                "first_text": _short(next((paragraph_text(p) for p in ps if paragraph_text(p).strip()), ""), 40)})

    label_count: Counter = Counter()
    for si, ti, tbl in loc.tables():
        cells = cells_of(tbl)
        rep["tables"].append({
            "path": f"s{si}/tbl[{ti}]", "rows": int(tbl.get("rowCnt", 0)), "cols": int(tbl.get("colCnt", 0)),
            "nested": any(a.tag == q("hp", "tc") for a in tbl.iterancestors()),
            "cells": [{"r": c.row, "c": c.col, "span": f"{c.rowspan}x{c.colspan}", "text": _short(c.text)} for c in cells],
        })
        index = {(c.row, c.col): c for c in cells}
        for c in cells:
            if not _is_label(c.text):
                continue
            right = index.get((c.row, c.col + c.colspan))
            if right is None:
                continue
            # 값 셀 판정: 비어 있거나, 라벨 셀과 테두리/배경(borderFill)이 다르거나, 라벨답지 않은 내용
            same_fill = right.el.get("borderFillIDRef") == c.el.get("borderFillIDRef")
            if norm(right.text) and same_fill and _is_label(right.text):
                continue
            key = norm(c.text)
            label_count[key] += 1
            spec = f"label:{key}" + (f"#{label_count[key]}" if label_count[key] > 1 else "")
            rep["candidates"].append({
                "label": c.text.strip(), "spec": spec,
                "path": f"s{si}/tbl[{ti}]/r[{right.row}]/c[{right.col}]",
                "current": _short(right.text),
            })

    for si, sec in enumerate(loc.secs):
        for fb in sec.iter(q("hp", "fieldBegin")):
            val, filled = field_value(fb)
            rep["fields"].append({"section": si, "name": fb.get("name", ""), "type": fb.get("type", ""),
                                  "value": val, "filled": filled, "where": _where(loc, si, fb)})
        for p in sec.iter(T_P):
            for m in _PLACEHOLDER.finditer(paragraph_text(p)):
                rep["placeholders"].append({"section": si, "name": m.group(1), "where": _where(loc, si, p) or f"s{si}/p[{sec.findall(T_P).index(p)}]"})
        for pic in sec.iter(q("hp", "pic")):
            img = pic.find(".//" + q("hc", "img"))
            rep["pictures"].append({"section": si, "binary": img.get("binaryItemIDRef") if img is not None else None,
                                    "in_table": any(a.tag == q("hp", "tc") for a in pic.iterancestors())})

    # 문단 항목('라벨 : 값')과 날짜 문단 — 병합 셀 안이나 본문에 있는 입력 위치
    rep["items"] = []
    for si, sec in enumerate(loc.secs):
        for p in sec.iter(T_P):
            txt = paragraph_text(p)
            if not txt.strip():
                continue
            m = _LABEL.match(txt)
            if m and 1 <= len(norm(m["label"])) <= 8:
                sp = find_item(txt, m["label"])
                if sp is not None:
                    rep["items"].append({"kind": "항목", "label": norm(m["label"]), "where": loc.where(p),
                                         "current": _short(sp.value, 40) if sp.value else "(빈칸)",
                                         "entry": {"at": loc.where(p), "after": norm(m["label"]), "value": "…"}})
            for dm, _style in iter_dates(txt):
                rep["items"].append({"kind": "날짜", "label": "", "where": loc.where(p),
                                     "current": dm.group(0).strip(),
                                     "entry": {"at": loc.where(p), "date": "YYYY-MM-DD"}})
            for bm in _BOX.finditer(txt):
                lab = bm["label"].strip()
                rep["items"].append({"kind": "선택", "label": lab, "where": loc.where(p),
                                     "current": bm.group(0).strip(),
                                     "entry": {"at": f"contains:{lab}", "check": lab}})

    for it in pkg.manifest_items():
        if it.get("href", "").startswith("BinData/"):
            rep["binaries"].append({"id": it.get("id"), "href": it.get("href"), "type": it.get("media-type")})
    return rep


def _where(loc: Locator, si: int, el) -> str:
    return loc.where(el)


_LABEL = re.compile(r"^[\s(（]*(?P<label>[가-힣A-Za-z][가-힣A-Za-z\s]{0,14}?)\s*[:：]")
_BOX = re.compile(r"[" + BOX_OFF + r"■]\s*(?P<label>[가-힣A-Za-z][가-힣A-Za-z0-9 ]{0,15}?)(?=\s{2,}|\s*[" + BOX_OFF + r"■]|\s*$)")


def to_markdown(rep: dict, cells: bool = False) -> str:
    L = [f"# 양식 분석: {rep['file']}", ""]
    L.append(f"- 섹션 {len(rep['sections'])}개, 표 {len(rep['tables'])}개, 채움 후보 {len(rep['candidates'])}건, "
             f"누름틀 {len(rep['fields'])}건, 자리표시자 {len(rep['placeholders'])}건, 그림 {len(rep['pictures'])}건")
    L += ["", "## 채움 후보 (라벨 오른쪽 셀)", "", "| 라벨 | 위치 지정 | 셀 경로 | 현재 내용 |", "| --- | --- | --- | --- |"]
    for c in rep["candidates"]:
        L.append(f"| {_short(c['label'], 20)} | `{c['spec']}` | `{c['path']}` | {c['current'] or '(빈 셀)'} |")
    if rep.get("items"):
        L += ["", "## 문단 항목·날짜 (표 칸이 아닌 입력 위치)", "", "| 종류 | 항목 | 놓인 곳 | 현재 내용 | 채움 항목 예 |", "| --- | --- | --- | --- | --- |"]
        for it in rep["items"]:
            e = it["entry"]
            ex = f'after: {e["after"]}' if "after" in e else (f'check: {e["check"]}' if "check" in e else "date")
            L.append(f"| {it['kind']} | {it['label']} | `{it['where']}` | {it['current']} | {ex} |")
    if rep["fields"]:
        L += ["", "## 누름틀", "", "| 위치 지정 | 놓인 곳 | 현재 값 |", "| --- | --- | --- |"]
        L += [f"| `field:{f['name']}` | `{f['where']}` | {f['value'] if f['filled'] else '(미입력)'} |" for f in rep["fields"]]
    if rep["placeholders"]:
        L += ["", "## 자리표시자", ""] + [f"- `{{{{{p['name']}}}}}` — `{p['where']}`" for p in rep["placeholders"]]
    L += ["", "## 표", "", "| 경로 | 행×열 | 중첩 | 첫 셀 |", "| --- | --- | --- | --- |"]
    for t in rep["tables"]:
        first = t["cells"][0]["text"] if t["cells"] else ""
        L.append(f"| `{t['path']}` | {t['rows']}×{t['cols']} | {'예' if t['nested'] else ''} | {first} |")
    if cells:
        for t in rep["tables"]:
            L += ["", f"### `{t['path']}`", ""]
            L += [f"- r{c['r']} c{c['c']} ({c['span']}): {c['text']}" for c in t["cells"]]
    if rep["pictures"]:
        L += ["", "## 그림", ""] + [f"- 섹션 {p['section']}: {p['binary']}{' (표 안)' if p['in_table'] else ''}" for p in rep["pictures"]]
    return "\n".join(L) + "\n"
