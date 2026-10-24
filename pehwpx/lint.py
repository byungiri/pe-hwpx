"""공문 규칙 검사 (설계서 4.5).

근거
- 「행정업무의 운영 및 혁신에 관한 규정」 제7조(문서 작성의 방법)
  ④ 숫자는 아라비아 숫자, ⑤ 날짜는 연·월·일 글자를 생략하고 온점으로, 시·분은 24시각제로 쌍점 구분.
- 같은 규정 시행규칙 제2조(공문서 작성의 방법)
  ① 항목 기호 1. → 가. → 1) → 가) → (1) → (가) → ① → ㉮ (필요 시 □, ○, -, ㆍ 등 특수기호 가능)
  ② 금액은 아라비아 숫자로 쓰고 괄호 안에 한글: 금113,560원(금일십일만삼천오백육십원)
- 같은 시행규칙 제4조(기안문의 구성) ⑤ 본문(붙임이 있으면 붙임)의 마지막 글자에서 한 글자 띄우고 '끝' 표시.
- 항목 기호와 내용 사이 1타, 하위 항목 2타 들여쓰기, 날짜의 월·일 앞 0 생략 등은 행정업무운영 편람(관행)으로 '권고'로 분류.
  (법령 조문은 작업 시점 원문으로 재확인할 것. 이 모듈 작성 시 확인: 규정 2026. 9. 29. 개정, 시행규칙 2023. 6. 28. 개정본)

검사 결과는 고치지 않고 위치·현재·권고안을 보고한다. 사용자가 승인한 규칙 코드만 fix 로 반영한다.

규칙 코드
  I1 항목 번호 순서(건너뜀·중복·시작 번호)       I2 상위 항목 없이 하위 기호 사용
  S1 항목 기호 뒤 띄어쓰기 없음(권고)
  D1 날짜 표기(2026. 9. 9. 형식)                 D2 '년·월·일' 글자 사용(권고, 증명서 등 특별한 사유면 무시)
  T1 시각 표기(24시각제 14:30)
  M1 금액 한글 병기 누락(본문 문장, 표 안 금액 제외)
  E1 '끝' 표시 없음                               E2 '끝' 표시 형식(한 글자 띄우고 '끝.')
  A1 붙임 수량 표기 누락(권고)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import q
from .locate import T_P, Locator, paragraph_text

SKIP_ANC = {q("hp", "fieldBegin"), q("hp", "header"), q("hp", "footer"), q("hp", "footNote"), q("hp", "endNote")}

_H = "가나다라마바사아자차카타파하"
_C1 = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_C2 = "㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷㉸㉹㉺㉻"
MARKERS = [  # (수준, 정규식, 값 변환)
    (0, re.compile(r"^(\d{1,2})\.(?!\d)(?!\s*\d{1,2}\s*\.)"), int),
    (1, re.compile(r"^([가나다라마바사아자차카타파하])\."), lambda s: _H.index(s) + 1),
    (2, re.compile(r"^(\d{1,2})\)(?!\d)"), int),
    (3, re.compile(r"^([가나다라마바사아자차카타파하])\)"), lambda s: _H.index(s) + 1),
    (4, re.compile(r"^\((\d{1,2})\)"), int),
    (5, re.compile(r"^\(([가나다라마바사아자차카타파하])\)"), lambda s: _H.index(s) + 1),
    (6, re.compile(r"^([①-⑳])"), lambda s: _C1.index(s) + 1),
    (7, re.compile(r"^([㉮-㉻])"), lambda s: _C2.index(s) + 1),
]
LEVEL_NAME = ["1.", "가.", "1)", "가)", "(1)", "(가)", "①", "㉮"]

RE_DATE = re.compile(r"(?<![\d.])((?:19|20)\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})(\s*\.)?(?![\d])")
RE_DATE_KO = re.compile(r"((?:19|20)\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
RE_TIME = re.compile(r"(오전|오후)?\s*(?<![\d.])(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?(?=$|[\s,.)~∼\-]|에|부터|까지|경|정각|이후|이전)")
RE_MONEY = re.compile(r"(금\s*)?(₩\s*)?(\d{1,3}(?:,\d{3})+|\d{4,})\s*원(?!\s*\(\s*금)(\s*\(([^()금][^()]*)\))?")
RE_END = re.compile(r"(\s*)[-－]?\s*끝\s*[-－]?\s*(\.?)\s*$")


def money_korean(n: int) -> str:
    """113560 → 일십일만삼천오백육십 (시행규칙 예시 방식: 자릿수마다 '일' 포함)."""
    digits = "영일이삼사오육칠팔구"
    small = ["", "십", "백", "천"]
    big = ["", "만", "억", "조", "경"]
    if n == 0:
        return "영"
    out, k = [], 0
    while n:
        n, chunk = divmod(n, 10000)
        if chunk:
            s = ""
            for i in range(3, -1, -1):
                d = (chunk // 10 ** i) % 10
                if d:
                    s += digits[d] + small[i]
            out.append(s + big[k])
        k += 1
    return "".join(reversed(out))


@dataclass
class Finding:
    code: str
    level: str      # 규정 | 권고
    where: str
    current: str
    suggest: str
    note: str = ""
    para: object = None
    span: tuple | None = None   # (start, end, 새 문자열) — 자동 수정 가능할 때


class _FastWhere:
    """읽기 전용 위치 표기 캐시: 표 칸·본문 문단의 경로를 한 번만 계산(큰 표 문서에서 검사 시간 단축)."""

    def __init__(self, loc):
        from .locate import T_TC, T_TBL, cells_of
        self.loc, self.T_TC, self.T_TBL = loc, T_TC, T_TBL
        self.cell = {}
        for si, ti, tbl in loc.tables():
            for c in cells_of(tbl):
                self.cell[c.el] = f"s{si}/tbl[{ti}]/r[{c.row}]/c[{c.col}]"
        self.top = {}
        for si, sec in enumerate(loc.secs):
            for k, p in enumerate(sec.findall(T_P)):
                self.top[p] = f"s{si}/p[{k}]"

    def where(self, el):
        for a in [el, *el.iterancestors()]:
            if a.tag == self.T_TC and a in self.cell:
                return self.cell[a]
            if a in self.top:
                return self.top[a]
        return self.loc.where(el)


def _paragraphs(pkg):
    loc = Locator(pkg)
    fw = _FastWhere(loc)
    for si, sec in enumerate(loc.secs):
        for p in sec.iter(T_P):
            if any(a.tag in SKIP_ANC for a in p.iterancestors()):
                continue
            yield fw, p


def check(pkg) -> list[Finding]:
    out: list[Finding] = []
    stacks: dict[int, list] = {}   # 문단을 담은 곳(본문 구역 또는 표 칸)별 번호 상태
    attach_stack: list[int | None] = [None] * 8
    in_attach = False
    end_seen = []
    last_body = None
    for loc, p in _paragraphs(pkg):
        raw = paragraph_text(p)
        text = raw.strip()
        if not text:
            continue
        where = loc.where(p)
        lead = len(raw) - len(raw.lstrip())
        body = text
        # 붙임 블록
        if re.match(r"^붙\s*임", text):
            in_attach = True
            attach_stack = [None] * 8
            m = re.match(r"^붙\s*임\s*[:：]?\s*", text)
            body = text[m.end():]
            lead += m.end()
        cont = p.getparent()
        top = cont.tag == q("hs", "sec")
        if re.match(r"^제\s*\d+\s*[장절편]", text) or "\t" in raw and re.search(r"\t\s*\d+\s*$", raw):
            if "\t" not in raw:
                stacks.clear()               # 장·절 제목(표 안 제목 상자 포함): 모든 번호 새로 시작
            stacks[id(cont)] = [None] * 8   # 목차 줄: 그 자리 번호만 새로 시작
            if "\t" in raw:
                continue
        st = attach_stack if in_attach else stacks.setdefault(id(cont), [None] * 8)
        # 항목 기호
        for lv, rx, conv in MARKERS:
            m = rx.match(body)
            if not m:
                continue
            if lv == 0 and int(m.group(1)) > 30:
                break
            v = conv(m.group(1))
            mark = m.group(0)
            rest = body[m.end():]
            if lv > 0 and st[lv - 1] is None and top and not in_attach:
                out.append(Finding("I2", "규정", where, mark + rest[:15],
                                   f"상위 항목({LEVEL_NAME[lv - 1]}) 없이 {LEVEL_NAME[lv]} 사용",
                                   "시행규칙 제2조제1항 항목 순서", p))
                st[lv - 1] = 0  # 같은 묶음의 다음 항목은 다시 보고하지 않음
            exp = (st[lv] + 1) if st[lv] is not None else 1
            if v != exp and (st[lv] is not None or top):  # 표 칸 안 목록은 시작 번호를 따지지 않음
                out.append(Finding("I1", "규정", where, mark + rest[:15],
                                   f"번호 순서: {LEVEL_NAME[lv].replace('1', str(exp)) if lv in (0, 2, 4) else exp}번째 기대",
                                   "번호 건너뜀·중복·시작 번호 확인", p))
            st[lv] = v
            for k in range(lv + 1, 8):
                st[k] = None
            if rest and not rest[0].isspace():
                s0 = lead + m.end()
                out.append(Finding("S1", "권고", where, mark + rest[:12], mark + " " + rest[:12],
                                   "항목 기호와 내용 사이 1타", p, (s0, s0, " ")))
            if in_attach and not re.search(r"\d+\s*부\s*\.?\s*(끝\.?)?\s*$", rest):
                out.append(Finding("A1", "권고", where, (mark + rest)[-20:], "… 1부.",
                                   "붙임 명칭 뒤 수량(○부) 표기", p))
            last_body = p
            break
        else:
            if in_attach and re.match(r"^붙\s*임", text):  # 붙임이 하나뿐인 경우: '붙임  ○○ 1부.'
                if body and not re.search(r"\d+\s*부\s*\.?\s*(끝\.?)?\s*$", body):
                    out.append(Finding("A1", "권고", where, body[-20:], "… 1부.", "붙임 명칭 뒤 수량(○부) 표기", p))
            elif in_attach:
                in_attach = False  # 항목이 아닌 문단이 나오면 붙임 목록 끝(발신명의·결문 등)
        # 날짜
        for m in RE_DATE.finditer(raw):
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            good = f"{y}. {mo}. {d}."
            cur = m.group(0)
            if cur != good:
                why = []
                if not m.group(4):
                    why.append("일 뒤 온점 누락")
                if re.search(r"\.\s*0\d", cur):
                    why.append("월·일 앞 0")
                if re.search(r"\.\S", cur.rstrip(".")):
                    why.append("온점 뒤 띄어쓰기")
                lvl = "규정" if not m.group(4) else "권고"
                out.append(Finding("D1", lvl, where, cur, good, ", ".join(why) or "날짜 표기", p,
                                   (m.start(), m.end(), good)))
        for m in RE_DATE_KO.finditer(raw):
            good = f"{m.group(1)}. {int(m.group(2))}. {int(m.group(3))}."
            out.append(Finding("D2", "권고", where, m.group(0), good,
                               "연·월·일 글자 생략(규정 제7조제5항, 증명서 등 특별한 사유면 무시)", p,
                               (m.start(), m.end(), good)))
        # 시각
        for m in RE_TIME.finditer(raw):
            ap, h, mi = m.group(1), int(m.group(2)), m.group(3)
            if h > 24:
                continue
            if ap == "오후" and h < 12:
                h += 12
            good = f"{h:02d}:{int(mi or 0):02d}"
            out.append(Finding("T1", "규정", where, m.group(0).strip(), good, "24시각제, 쌍점 구분(규정 제7조제5항)", p,
                               (m.start() + (len(m.group(0)) - len(m.group(0).lstrip())), m.end(), good)))
        # 금액
        in_cell = any(a.tag == q("hp", "tc") for a in p.iterancestors())
        for m in ([] if in_cell else RE_MONEY.finditer(raw)):  # 표(내역서 등) 안 금액은 제외 — 본문 문장의 금액만
            n = int(m.group(3).replace(",", ""))
            if n < 1000:
                continue
            extra = m.group(5)  # 바로 뒤 괄호(예: 부가가치세 포함)는 한글 병기 괄호 안에 합친다
            good = f"금{n:,}원(금{money_korean(n)}원" + (f", {extra.strip()})" if extra else ")")
            out.append(Finding("M1", "규정", where, m.group(0), good, "금액 한글 병기(시행규칙 제2조제2항)", p,
                               (m.start(), m.end(), good)))
        # 끝 표시
        me = RE_END.search(raw)
        if me and "끝" in raw[me.start():]:
            end_seen.append((p, where))
            in_attach = False
            seg = raw[me.start():]
            good_tail = "  끝."
            if seg != good_tail:
                out.append(Finding("E2", "권고" if seg.strip() in ("끝.", "끝") else "규정", where, repr(seg), repr(good_tail),
                                   "마지막 글자에서 한 글자(2타) 띄우고 '끝.'(시행규칙 제4조제5항)", p,
                                   (me.start(), len(raw), good_tail)))
    if not end_seen:
        out.append(Finding("E1", "규정", last_body is not None and _FastWhere(Locator(pkg)).where(last_body) or "-", "(없음)",
                           "본문(붙임) 마지막 글자 뒤 '  끝.'", "시행규칙 제4조제5항", last_body,
                           None))
    return out


def fix(pkg, findings: list[Finding], codes: set[str]) -> tuple[list[Finding], set[str], list[str]]:
    """승인된 코드의 자동 수정. 같은 문단은 뒤쪽 위치부터 바꾼다."""
    from .fill import FillError, replace_span
    done, allowed, skipped = [], set(), []
    by_para: dict[int, list[Finding]] = {}
    for f in findings:
        if f.code in codes and f.span is not None and f.para is not None:
            by_para.setdefault(id(f.para), []).append(f)
    loc = Locator(pkg)
    for fs in by_para.values():
        p = fs[0].para
        for f in sorted(fs, key=lambda x: -x.span[0]):
            s, e, new = f.span
            try:
                replace_span(p, s, e, new)
                done.append(f)
                allowed.add(f.where)
            except FillError as ex:
                skipped.append(f"{f.code} {f.where} {f.current}: {ex}")
    if "E1" in codes:
        for f in findings:
            if f.code == "E1" and f.para is not None:
                txt = paragraph_text(f.para)
                replace_span(f.para, len(txt.rstrip()), len(txt), "  끝.")
                done.append(f)
                allowed.add(loc.where(f.para))
    for si, name in enumerate(pkg.section_names()):
        pkg.touch(name)
    return done, allowed, skipped


def report(findings: list[Finding]) -> str:
    if not findings:
        return "위반·권고 사항 없음"
    lines = ["| 코드 | 구분 | 위치 | 현재 | 권고안 | 비고 |", "| --- | --- | --- | --- | --- | --- |"]
    for f in findings:
        cur = str(f.current).replace("|", "／")[:30]
        sug = str(f.suggest).replace("|", "／")[:40]
        lines.append(f"| {f.code} | {f.level} | `{f.where}` | {cur} | {sug} | {f.note}{' (자동 수정 가능)' if f.span else ''} |")
    cnt = {}
    for f in findings:
        cnt[f.code] = cnt.get(f.code, 0) + 1
    lines.append("")
    lines.append("집계: " + ", ".join(f"{k} {v}건" for k, v in sorted(cnt.items())))
    return "\n".join(lines)


# ---------------------------------------------------------------- 붙임 목록 정렬
def align_attachments(pkg, pdf: str | None = None) -> list[str]:
    """'붙임 : 1. ○○' 다음 줄의 '2. ○○' … 를 첫 항목 번호 위치에 맞춘다.
    둘째 줄부터의 앞 공백을 지우고 문단 왼쪽 여백을 첫 항목 번호 위치로 둔다(공백으로 맞추면 글꼴에 따라 어긋남).
    pdf(한글로 변환한 PDF)를 주면 실제 위치로, 없으면 글자 폭 추정으로 계산한다."""
    import copy
    from lxml import etree
    from .fill import replace_span
    from .outline import Writer
    loc = Locator(pkg)
    w = Writer(pkg)
    notes = []
    for sec in loc.secs:
        ps = sec.findall(T_P)
        for i, p in enumerate(ps):
            t = paragraph_text(p)
            m = re.match(r"^(\s*붙\s*임\s*[:：]?\s*)(\d+\.|[가나다라마바사아자차카타파하]\.)", t)
            if not m:
                continue
            prefix = m.group(1)
            follow = []
            for p2 in ps[i + 1:]:
                t2 = paragraph_text(p2)
                if re.match(r"^\s+(\d+\.|[가나다라마바사아자차카타파하]\.)", t2):
                    follow.append(p2)
                else:
                    break
            if not follow:
                continue
            target = None
            if pdf:
                from .image import pdf_words
                words = pdf_words(pdf)
                for k, wd in enumerate(words):
                    if wd[1].startswith("붙") and k + 3 < len(words):
                        line = [x for x in words if x[0] == wd[0] and abs((x[3] + x[5]) / 2 - (wd[3] + wd[5]) / 2) < 3]
                        mk = next((x for x in sorted(line, key=lambda x: x[2])
                                   if re.match(r"^(\d+\.|[가나다라마바사아자차카타파하]\.)$", x[1])), None)
                        if mk:
                            target = int((mk[2] - wd[2]) * 100)  # pt → HWPUNIT, '붙임' 시작 기준
                            break
            if target is None:
                run0 = next((r for r in p.findall(q("hp", "run")) if r.findall(q("hp", "t"))), None)
                cp = w.cps.get(run0.get("charPrIDRef")) if run0 is not None else None
                h = int(cp.get("height", 1000)) if cp is not None else 1000
                em = sum(1.0 if ord(ch) > 0x2000 else (0.5 if ch == " " else 0.33 if ch in ":：" else 0.55)
                         for ch in prefix.lstrip())  # 한글 1, 빈칸 0.5, 쌍점 0.33 (명조 계열 실측)
                target = int(em * h)
            base_left = w._base_left(p.get("paraPrIDRef"))
            for p2 in follow:
                t2 = paragraph_text(p2)
                lead = len(t2) - len(t2.lstrip())
                if lead:
                    replace_span(p2, 0, lead, "")
                pid = w._parapr(p2.get("paraPrIDRef"), base_left + target, 0)
                p2.set("paraPrIDRef", pid)
            notes.append(f"{loc.where(p)}: 붙임 {len(follow) + 1}개 항목, 둘째 줄부터 왼쪽 여백 {target / 7200 * 25.4:.2f}mm"
                         + (" (PDF 실측)" if pdf else " (추정)"))
    for name in pkg.section_names():
        pkg.touch(name)
    return notes
