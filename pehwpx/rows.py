"""반복행 (설계서 4.3): 경력·참여실적·검토항목처럼 개수가 바뀌는 표 행을 채우고 늘리거나 줄인다.

채움 파일 항목
  {"rows": "s0/tbl[3]/r[17]",          반복 구간의 첫 행(견본 행)
   "cols": [1, 2, 5, 8],               값을 넣을 열(논리 좌표 c). 자료가 dict 이면 {"키": 열} 로 지정
   "data": [["기관", "직위", ...], ...] 또는 "from": "careers" (--data JSON 의 목록)
   "overflow": "error" | "grow" | "annex",   행이 모자랄 때 (기본 error)
   "trim": false,                      남는 빈 행 삭제 여부 (기본 유지)
   "annex_text": "별지 참조",            annex 일 때 마지막 행 첫 열에 넣을 문구
   "block": 4,                         반복 구간 행 수를 직접 지정 (생략 시 같은 열 구성의 연속 행을 자동 인식)
   "fit": true}                        각 칸에 칸 폭 맞춤 적용(채움 파일 최상위 fit 도 적용)

동작 원칙
- 구간은 견본 행과 같은 열 구성(병합 없음)을 가진 연속 행이다. 그 밖의 행은 내용·구조를 그대로 둔다.
- 행을 늘릴 때는 구간 마지막 행을 복제해 바로 아래에 넣고, 위에서 내려오는 세로 병합 칸(예: '경력사항')의
  병합 범위, 아래 행들의 행 번호, 표의 행 수·높이를 함께 고친다. 줄일 때는 그 반대.
- 발주기관 양식은 행 수 변경이 허용되지 않는 경우가 많으므로 기본값은 error(행 부족 시 중단·보고)다.
  사용자가 행 추가를 허락하면 grow, 별지로 돌리라고 하면 annex 를 쓴다.
- 작업 후 구간 밖 모든 행의 열 구성·내용이 원본과 같은지(아래 행은 늘어난 만큼 밀린 위치에서) 확인한다.
"""

from __future__ import annotations

import copy
import re

from lxml import etree

from . import q
from .locate import (T_P, T_TC, T_TR, LocateError, cell_paragraphs, cells_of,
                     paragraph_text)

T_SZ, T_CSZ = q("hp", "sz"), q("hp", "cellSz")
T_ADDR, T_SPAN = q("hp", "cellAddr"), q("hp", "cellSpan")
T_LSA = q("hp", "linesegarray")


class RowsError(ValueError):
    pass


def _row_of(tr) -> int:
    tc = tr.find(T_TC)
    return int(tc.find(T_ADDR).get("rowAddr")) if tc is not None else -1


def _sig(tbl, r: int):
    """r 행에서 시작하는 칸들의 (열, 열병합) 구성. 세로 병합 칸이 있으면 None."""
    cs = [c for c in cells_of(tbl) if c.row == r]
    if not cs or any(c.rowspan != 1 for c in cs):
        return None
    return tuple(sorted((c.col, c.colspan) for c in cs))


def _other_text_ok(tbl, r: int, cols) -> bool:
    """값 열(cols) 밖의 칸이 비었거나 순번(숫자)만 있으면 반복 행으로 본다(라벨 행 제외)."""
    if cols is None:
        return True
    for c in cells_of(tbl):
        if c.row == r and c.col not in cols:
            t = "".join(paragraph_text(p) for p in cell_paragraphs(c.el)).strip()
            if t and not re.fullmatch(r"\d+\.?", t):
                return False
    return True


def number_cols(tbl, rows: list[int], cols) -> dict[int, int]:
    """값 열 밖에서 1, 2, 3… 처럼 순번이 이어지는 열 → {열: 마지막 번호}."""
    out = {}
    if cols is None:
        return out
    cand = {c.col for c in cells_of(tbl) if c.row == rows[0] and c.col not in cols}
    for col in cand:
        nums = []
        for r in rows:
            c = next(x for x in cells_of(tbl) if x.row == r and x.col == col)
            t = "".join(paragraph_text(p) for p in cell_paragraphs(c.el)).strip().rstrip(".")
            nums.append(int(t) if t.isdigit() else None)
        if None not in nums and all(b - a == 1 for a, b in zip(nums, nums[1:])):
            out[col] = nums[-1]
    return out


def find_block(tbl, start: int, block: int | None = None, cols=None) -> list[int]:
    sig = _sig(tbl, start)
    if sig is None:
        raise RowsError(f"r[{start}] 은 세로 병합 칸이 있어 반복 견본 행으로 쓸 수 없음")
    nrows = int(tbl.get("rowCnt"))
    rows = [start]
    if block:
        for r in range(start + 1, start + block):
            if r >= nrows or _sig(tbl, r) != sig:
                raise RowsError(f"block={block} 이지만 r[{r}] 의 열 구성이 견본 행과 다름")
            rows.append(r)
        return rows
    r = start + 1
    while r < nrows and _sig(tbl, r) == sig and _other_text_ok(tbl, r, cols):
        rows.append(r)
        r += 1
    return rows


def _tr_at(tbl, r: int):
    return next((tr for tr in tbl.findall(T_TR) if _row_of(tr) == r), None)


def _row_height(tr) -> int:
    return max(int(tc.find(T_CSZ).get("height")) for tc in tr.findall(T_TC))


def _add_cell_height(tc, delta: int) -> None:
    sz = tc.find(T_CSZ)
    if sz is not None and sz.get("height"):
        sz.set("height", str(max(1, int(sz.get("height")) + delta)))


def _set_tbl_rows(tbl, delta_rows: int, delta_h: int) -> None:
    tbl.set("rowCnt", str(int(tbl.get("rowCnt")) + delta_rows))
    sz = tbl.find(T_SZ)
    if sz is not None and sz.get("height"):
        sz.set("height", str(max(0, int(sz.get("height")) + delta_h)))
    p = next((a for a in tbl.iterancestors() if a.tag == T_P), None)
    if p is not None and p.find(T_LSA) is not None:  # 표를 품은 문단의 줄 배치 캐시 → 한글이 다시 계산
        p.remove(p.find(T_LSA))


def _clear_cell(tc) -> None:
    ps = cell_paragraphs(tc)
    for p in ps[1:]:
        p.getparent().remove(p)
    p = ps[0]
    ts = [t for r in p.findall(q("hp", "run")) for t in r.findall(q("hp", "t"))]
    for i, t in enumerate(ts):
        for ch in list(t):
            t.remove(ch)
        t.text = ""
        if i:
            t.getparent().remove(t)
    for run in p.findall(q("hp", "run")):  # 그림·개체가 든 런은 지운다(복제 행에 원본 그림이 남지 않게)
        if any(ch.tag != q("hp", "t") for ch in run):
            for ch in list(run):
                if ch.tag != q("hp", "t"):
                    run.remove(ch)
    if p.find(T_LSA) is not None:
        p.remove(p.find(T_LSA))


def grow(tbl, last: int, k: int) -> None:
    """last 행을 k번 복제해 바로 아래에 넣는다."""
    for _ in range(k):
        tr_last = _tr_at(tbl, last)
        h = _row_height(tr_last)
        for c in cells_of(tbl):
            if c.row < last <= c.row + c.rowspan - 1:  # 위에서 내려와 last 행을 덮는 세로 병합 칸
                c.el.find(T_SPAN).set("rowSpan", str(c.rowspan + 1))
                _add_cell_height(c.el, h)  # 병합 칸 높이도 늘린 행만큼 키운다
            elif c.row > last:
                c.el.find(T_ADDR).set("rowAddr", str(c.row + 1))
        new = copy.deepcopy(tr_last)
        for tc in new.findall(T_TC):
            tc.find(T_ADDR).set("rowAddr", str(last + 1))
            _clear_cell(tc)
        tr_last.addnext(new)
        last += 1
        _set_tbl_rows(tbl, 1, h)


def shrink(tbl, last: int, k: int) -> None:
    """last 행부터 위로 k개 행을 지운다."""
    for _ in range(k):
        tr = _tr_at(tbl, last)
        h = _row_height(tr)
        for c in cells_of(tbl):
            if c.row < last <= c.row + c.rowspan - 1:
                c.el.find(T_SPAN).set("rowSpan", str(c.rowspan - 1))
                _add_cell_height(c.el, -h)  # 병합 칸 높이를 남겨 두면 한글이 남은 행을 그만큼 늘린다
            elif c.row > last:
                c.el.find(T_ADDR).set("rowAddr", str(c.row - 1))
        tr.getparent().remove(tr)
        last -= 1
        _set_tbl_rows(tbl, -1, -h)


def row_snapshot(tbl) -> dict[int, tuple]:
    """행별 (열, 열병합, 내용) — 세로 병합 범위는 제외(반복행 처리로 바뀌는 값)."""
    out: dict[int, list] = {}
    for c in cells_of(tbl):
        txt = "\n".join(paragraph_text(p) for p in cell_paragraphs(c.el))
        out.setdefault(c.row, []).append((c.col, c.colspan, txt))
    return {r: tuple(sorted(v)) for r, v in out.items()}


def check_outside(before: dict, after: dict, first: int, n_before: int, n_after: int) -> list[str]:
    """구간 [first, first+n) 밖 행이 그대로인지(아래 행은 n_after-n_before 만큼 밀린 위치) 확인."""
    bad, d = [], n_after - n_before
    for r, v in before.items():
        if first <= r < first + n_before:
            continue
        r2 = r if r < first else r + d
        if after.get(r2) != v:
            bad.append(f"r[{r}]→r[{r2}]")
    return bad


def parse_start(spec: str) -> tuple[str, int]:
    m = re.match(r"^(s\d+/tbl\[\d+\])/r\[(\d+)\]$", spec.strip())
    if not m:
        raise RowsError(f"rows 위치는 's0/tbl[k]/r[i]' 형식: {spec}")
    return m.group(1), int(m.group(2))
