"""양식 문단 안의 입력 형식 해석: '라벨 : 값', 날짜(빈칸 포함), 체크박스.

모두 순수 문자열 함수다. 반환하는 위치는 paragraph_text() 기준 문자 위치.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass


def disp_width(s: str) -> int:
    """화면 폭(한글·전각 2, 그 외 1). 빈칸 맞춤 계산용."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _label_re(label: str) -> str:
    return r"\s*".join(re.escape(ch) for ch in re.sub(r"\s", "", label))


# ================================================================ 라벨 : 값
@dataclass
class ItemSpan:
    start: int          # 값 시작(빈 값이면 삽입 위치)
    end: int            # 값 끝
    value: str
    gap: int            # 빈 값일 때 콜론 뒤~안내문 앞 공백 수 (값이 있으면 0)


def find_item(text: str, label: str) -> ItemSpan | None:
    """'성   명 :            (인 또는 성명)', '( 용 도 :  값  )', '상호명 :  값      ' 등에서 값 구간을 찾는다.

    규칙: 콜론 뒤 공백을 건너뛴 본문을 '두 칸 이상 공백'에서 자른 앞부분이 값이다.
    - 본문이 괄호로 둘러싸인 안내문('(인 또는 성명)')뿐이면 빈 값으로 본다.
    - 값 끝의 닫는 괄호는 값 안에 여는 괄호가 없으면 값에서 제외한다.
    """
    m = re.search(r"(?:^|(?<=[\s(（]))" + _label_re(label) + r"\s*[:：]", text)
    if not m:
        return None
    c = m.end()
    rest = text[c:]
    lead = len(rest) - len(rest.lstrip())
    body = rest[lead:]
    cut = re.search(r"\s{2,}", body)
    value = body[: cut.start()] if cut else body.rstrip()
    if value.endswith((")", "）")) and "(" not in value and "（" not in value:
        value = value[:-1].rstrip()
    annotation_only = bool(re.fullmatch(r"[(（][^()（）]*[)）]", value)) and lead >= 2
    if not value or annotation_only:
        return ItemSpan(c, c + lead, "", lead)
    s = c + lead
    return ItemSpan(s, s + len(value), value, 0)


def render_item(span: ItemSpan, value: str) -> str:
    """빈 값 칸에 넣을 문자열: 한 칸 띄우고 값, 남은 폭만큼 공백(최소 2칸)을 유지해 안내문 위치를 보존."""
    if span.gap == 0:
        return value
    remain = max(2, span.gap - 1 - disp_width(value))
    return " " + value + " " * remain


# ================================================================ 날짜 (빈칸 포함)
_DATE_KO = re.compile(r"(?P<y>\d{4}|(?:19|20)(?=\s+년))(?P<a>\s*)년(?P<b>\s*)(?P<m>\d{0,2})(?P<c>\s*)월(?P<e>\s*)(?P<d>\d{0,2})(?P<f>\s*)일")
_DATE_DOT = re.compile(r"(?P<y>\d{4}|(?:19|20)(?=\s+\.\s+\.))(?P<a>\s*)\.(?P<b>\s*)(?P<m>\d{0,2})(?P<c>\s*)\.(?P<e>\s*)(?P<d>\d{0,2})(?P<f>\s*)(?P<g>\.?)")


def iter_dates(text: str):
    """(match, 형식) — 형식 'ko' 또는 'dot'. 월·일이 빈칸인 양식 날짜도 포함."""
    spans = []
    for style, rx in (("ko", _DATE_KO), ("dot", _DATE_DOT)):
        for m in rx.finditer(text):
            if style == "dot" and not m["m"] and not m["d"] and not m["g"]:
                continue  # '2026.' 같은 단독 연도 표기 제외
            if any(not (m.end() <= s or m.start() >= e) for s, e, _, _ in spans):
                continue
            spans.append((m.start(), m.end(), m, style))
    for s, e, m, style in sorted(spans, key=lambda x: x[0]):
        yield m, style


def _adj(ws: str, old: str, new: str) -> str:
    """숫자 자릿수가 바뀐 만큼 앞 공백을 조정해 뒤 글자 위치를 유지(공백이 있던 곳은 최소 1칸)."""
    diff = len(new) - len(old)
    if not ws:
        return ws
    return " " * max(1, len(ws) - diff)


def _num(orig: str, n: int, pad: bool) -> str:
    return f"{n:02d}" if (pad or orig.startswith("0")) and n < 10 else str(n)


def render_date(m: re.Match, style: str, d: dt.date) -> str:
    pad = m["m"].startswith("0") or m["d"].startswith("0")
    a = m["a"]
    if len(m["y"]) == 2:  # '20  .   .   .' 처럼 연도 앞 두 자리만 인쇄된 양식: 연도 빈칸을 연도 숫자가 차지
        a = " " * max(0, len(a) - 2)
    mm, dd = _num(m["m"], d.month, pad), _num(m["d"], d.day, pad)
    if style == "ko":
        return (f"{d.year}{a}년{_adj(m['b'], m['m'], mm)}{mm}{m['c']}월"
                f"{_adj(m['e'], m['d'], dd)}{dd}{m['f']}일")
    return (f"{d.year}{a}.{_adj(m['b'], m['m'], mm)}{mm}{m['c']}."
            f"{_adj(m['e'], m['d'], dd)}{dd}{m['f']}{m['g'] or ''}")


def parse_date(v) -> dt.date:
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    if s in ("today", "오늘"):
        return dt.date.today()
    return dt.date.fromisoformat(s)


# ================================================================ 체크박스
BOX_OFF = "□☐"
BOX_ON = "■"


def find_box(text: str, label: str) -> int | None:
    """'□ 동의함' 의 상자 문자 위치. 라벨 뒤에 글자가 더 붙은 '동의함X' 는 제외(경계 확인)."""
    m = re.search(r"([" + BOX_OFF + BOX_ON + r"■☑✔✓])\s*" + _label_re(label) + r"(?![가-힣A-Za-z])", text)
    return m.start(1) if m else None
