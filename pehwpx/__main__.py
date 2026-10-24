"""명령행 진입점: python -m pehwpx <명령> ...

명령
  scan <양식.hwpx> [--cells] [--json]      양식 분석, 채움 후보 목록
  fill <양식.hwpx> <채움.json|yaml> [--data 자료.json] [-o 결과.hwpx]
                                           채움 + 구조 검증 + 변경 범위 대조
  set <양식.hwpx> <위치> [값] [--after 라벨 | --date YYYY-MM-DD|today] [-o 결과.hwpx]
                                           한 곳만 빠르게 채움
  register <양식.hwpx> [-o 양식맵.json] [--id ID] [--title 제목]
                                           양식맵 초안 생성(개인정보 미포함)
  match <양식.hwpx> [--maps 폴더 ...]       등록된 양식맵 중 일치하는 것 찾기
  make <양식.hwpx> [--map 양식맵.json] [--set 항목=값 ...] [--data 자료.json] [-o 결과.hwpx]
                                           양식맵 항목 이름으로 작성 (양식맵 생략 시 자동 대조)
  fields <양식맵.json>                       양식맵 항목 목록
  stamp <문서.hwpx> <배치.json> [--pdf 한글변환.pdf] [--assets 이미지폴더] [-o 결과.hwpx]
                                           직인·서명·체크 이미지 배치 (PDF 가 있으면 실측 좌표)
  locate <문서.hwpx> <위치>                 위치 표기 해석 결과 확인
  verify <원본.hwpx> [<결과.hwpx>]          구조 검증 (+ 원본 대비 변경 범위 diff)
  roundtrip <문서.hwpx> [-o 출력]           열기→저장 왕복 후 무변경 확인 (보존성 시험)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from . import __version__
from .locate import Locator, LocateError, cell_text, field_value, paragraph_text
from .package import HwpxPackage
from .scan import scan, to_markdown
from .fill import Filler, FillError, load_map
from .verify import check_scope, check_structure, diff, format_diff
from . import formmap


def _out(s: str) -> None:
    sys.stdout.write(s if s.endswith("\n") else s + "\n")


def cmd_scan(a) -> int:
    rep = scan(HwpxPackage.open(a.file))
    _out(json.dumps(rep, ensure_ascii=False, indent=1) if a.json else to_markdown(rep, cells=a.cells))
    return 0


def cmd_locate(a) -> int:
    loc = Locator(HwpxPackage.open(a.file))
    try:
        t = loc.resolve(a.spec)
    except LocateError as e:
        _out(f"실패: {e}")
        return 1
    if t.kind == "field":
        val, filled = field_value(t.el)
        text = val if filled else "(미입력)"
    else:
        text = cell_text(t.el) if t.kind == "cell" else paragraph_text(t.el) if t.kind in ("paragraph", "placeholder", "item") else ""
    _out(f"{t.kind}\t{t.path}\t{text!r}")
    return 0


def cmd_verify(a) -> int:
    rc = 0
    target = a.result or a.original
    errs = check_structure(target)
    _out("구조 검증: " + ("통과" if not errs else "실패"))
    for e in errs:
        _out("  - " + e)
        rc = 1
    if a.result:
        rep = diff(a.original, a.result)
        _out("변경 범위: " + format_diff(rep))
    return rc


def _default_out(src: str) -> str:
    base, ext = os.path.splitext(os.path.basename(src))
    return base + "_작성" + ext


def order_items(items: list[dict]) -> list[dict]:
    """채움 파일의 모든 위치는 원본 문서 기준이다. 반복행이 행을 늘리거나 줄이면 아래 행 번호가 밀리므로
    일반 항목을 먼저 넣고, 반복행은 같은 표 안에서 아래쪽 구간부터 처리한다(위쪽 구간의 행 수 변화가 아래 위치를 바꾸지 않게)."""
    from .rows import parse_start
    plain = [it for it in items if "rows" not in it]
    rows = [it for it in items if "rows" in it]

    def key(it):
        try:
            t, r = parse_start(it["rows"])
            return (t, -r)
        except Exception:
            return ("", 0)
    return plain + sorted(rows, key=key)


def run_fill(src: str, items: list[dict], data: dict | None, out: str) -> int:
    pkg = HwpxPackage.open(src)
    f = Filler(pkg)
    errors = []
    for it in order_items(items):
        try:
            f.apply(it, data)
        except (FillError, KeyError) as e:
            errors.append(f"{it.get('at') or it.get('rows')}: {e}")
    if errors:
        _out("채움 실패 — 저장하지 않음")
        for e in errors:
            _out("  - " + e)
        return 1
    f.finish()
    if os.path.abspath(out) == os.path.abspath(src):
        _out("원본 덮어쓰기는 허용하지 않음: -o 로 다른 파일명을 지정")
        return 1
    pkg.save(out)
    _out(f"결과: {out}")
    _out("")
    _out("| 위치 지정 | 종류 | 놓인 곳 | 이전 | 이후 |")
    _out("| --- | --- | --- | --- | --- |")
    for r in f.applied:
        b = r.before.replace("\n", " ⏎ ").replace("|", "／")
        aft = r.after.replace("\n", " ⏎ ").replace("|", "／")
        _out(f"| `{r.spec}` | {r.kind} | `{r.where}` | {b[:40]} | {aft[:40]} |")
    for r in f.applied:
        for rec in getattr(r, "overflow", None) or []:
            _out(f"- 별지 대상({r.spec}): " + " / ".join(map(str, rec.values() if isinstance(rec, dict) else rec)).replace("\n", " "))
    errs = check_structure(out)
    rep = diff(src, out)
    outside = check_scope(rep, sorted(f.allowed))
    _out("")
    _out("구조 검증: " + ("통과" if not errs else "실패 " + "; ".join(errs)))
    _out(f"변경 범위: 변경 노드 {len(rep.changes)}건, 지정 위치 밖 변경 {len(outside)}건 → " + ("통과" if not outside else "실패"))
    for c in outside:
        _out(f"  - {c.part} {c.locpath or c.xpath}: {c.what}")
    return 0 if not errs and not outside else 1


def cmd_fill(a) -> int:
    data = None
    if a.data:
        with open(a.data, encoding="utf-8") as fh:
            data = json.load(fh)
    return run_fill(a.file, load_map(a.map), data, a.output or _default_out(a.file))


def cmd_set(a) -> int:
    item = {"at": a.spec}
    if a.date:
        item["date"] = a.date
    else:
        if a.value is None:
            _out("값이 필요함")
            return 1
        item["value"] = a.value
        if a.after:
            item["after"] = a.after
    return run_fill(a.file, [item], None, a.output or _default_out(a.file))


def cmd_register(a) -> int:
    m = formmap.register(HwpxPackage.open(a.file), a.id or "", a.title or "")
    out = a.output or (os.path.splitext(os.path.basename(a.file))[0] + ".map.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=2)
    _out(f"양식맵 초안: {out}")
    _out(formmap.describe(m))
    _out("\n다음 단계: 항목 이름을 업무 용어로 바꾸고, 매번 바뀌는 항목에 \"required\": true, 고정 정보에 \"from\" 을 지정한다.")
    return 0


def cmd_match(a) -> int:
    res = formmap.best_match(HwpxPackage.open(a.file), a.maps)
    if not res:
        _out("등록된 양식맵 없음")
        return 1
    _out("| 양식맵 | 점수 | 항목 위치 | 라벨 | 문구 | 파일 |")
    _out("| --- | --- | --- | --- | --- | --- |")
    for r in res:
        m = r["map"]
        _out(f"| {m.get('title')} | {r['score']:.2f} | {len(r['fields_ok'])}/{len(m['fields'])} | {r['labels']} | {r['phrases']} | {os.path.basename(m['_path'])} |")
    top = res[0]
    if top["score"] >= formmap.MATCH_THRESHOLD:
        _out(f"\n일치: {top['map'].get('title')} ({os.path.basename(top['map']['_path'])})")
        _out(formmap.describe(top["map"]))
        if top["fields_missing"]:
            _out("찾지 못한 항목: " + ", ".join(top["fields_missing"]))
        return 0
    _out(f"\n일치하는 양식맵 없음 (기준 {formmap.MATCH_THRESHOLD})")
    return 1


def cmd_make(a) -> int:
    pkg = HwpxPackage.open(a.file)
    if a.map:
        m = formmap.load(a.map)
        sc = formmap.score(pkg, m)
        if sc["score"] < formmap.MATCH_THRESHOLD:
            _out(f"경고: 양식과 양식맵 일치도 {sc['score']:.2f} — 찾지 못한 항목: {', '.join(sc['fields_missing']) or '없음'}")
    else:
        res = formmap.best_match(pkg, a.maps)
        if not res or res[0]["score"] < formmap.MATCH_THRESHOLD:
            _out("일치하는 양식맵 없음: --map 으로 지정하거나 register 로 먼저 등록")
            return 1
        m = res[0]["map"]
        _out(f"양식맵 자동 선택: {m.get('title')} ({os.path.basename(m['_path'])})")
    values = {}
    for kv in a.set or []:
        if "=" not in kv:
            _out(f"--set 형식 오류(항목=값): {kv}")
            return 1
        k, v = kv.split("=", 1)
        values[k.strip()] = v
    data = None
    if a.data:
        with open(a.data, encoding="utf-8") as fh:
            data = json.load(fh)
    try:
        items, missing = formmap.build_items(m, values, data)
    except formmap.MapError as e:
        _out(f"실패: {e}")
        return 1
    if missing:
        _out("필수 항목 값이 없음 — 저장하지 않음: " + ", ".join(missing))
        for n in missing:
            _out(f"  - {n}: {m['fields'][n].get('desc', '')}")
        return 2
    if not items:
        _out("채울 항목 없음")
        return 1
    return run_fill(a.file, items, data, a.output or _default_out(a.file))


def cmd_fields(a) -> int:
    _out(formmap.describe(formmap.load(a.map)))
    return 0


def cmd_stamp(a) -> int:
    import random
    from .image import ImageError, Roles, Stamper
    with open(a.spec_file, encoding="utf-8") as fh:
        spec = json.load(fh)
    items = spec.get("stamps", spec) if isinstance(spec, dict) else spec
    roles = {}
    if a.assets and os.path.exists(os.path.join(a.assets, "assets.json")):
        with open(os.path.join(a.assets, "assets.json"), encoding="utf-8") as fh:
            roles = json.load(fh)
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(1, 10**6)
    rr = Roles(roles, seed)
    pkg = HwpxPackage.open(a.file)
    st = Stamper(pkg)
    errors = []
    for it in items:
        opts = {"width_mm": 15.0, "dx_mm": 0.0, "dy_mm": 0.0, "rotate_deg": 0.0, "remove_bg": True}
        name = it["image"]
        try:
            if name.startswith("@"):  # 역할 이름: @seal, @signature, @name, @check (assets.json)
                r = rr.resolve(name[1:], it.get("jitter_mm"), it.get("rotate_max_deg"))
                name = r.pop("file")
                opts.update(r)
            # 배치 파일 값: 폭·회전은 덮어쓰고, 이동(dx/dy)은 손 느낌 흔들림에 더한다
            for k in ("width_mm", "rotate_deg"):
                if k in it:
                    opts[k] = float(it[k])
            if "scale" in it:  # 역할 기본 크기의 배수 (예: 서명 1.5배)
                opts["width_mm"] *= float(it["scale"])
            for k in ("dx_mm", "dy_mm"):
                if k in it:
                    opts[k] += float(it[k])
            img = name if os.path.isabs(name) or not a.assets else os.path.join(a.assets, name)
            st.stamp(img, it["near"], opts["width_mm"], on=it.get("on"), nth=int(it.get("nth", 1)), pdf=a.pdf,
                     dx_mm=opts["dx_mm"], dy_mm=opts["dy_mm"], rotate_deg=opts["rotate_deg"],
                     remove_bg=bool(it.get("remove_bg", opts["remove_bg"])),
                     fit_cell=it.get("fit") == "cell", margin_mm=float(it.get("margin_mm", 1.0)))
        except (ImageError, KeyError) as e:
            errors.append(f"{it.get('near')}: {e}")
    if errors:
        _out("배치 실패 — 저장하지 않음")
        for e in errors:
            _out("  - " + e)
        return 1
    out = a.output or _default_out(a.file)
    if os.path.abspath(out) == os.path.abspath(a.file):
        _out("원본 덮어쓰기는 허용하지 않음: -o 로 다른 파일명을 지정")
        return 1
    pkg.save(out)
    _out(f"결과: {out}  (무작위 시드 {seed} — 같은 배치를 재현하려면 --seed {seed})\n")
    _out("| 이미지 | 기준 문구 | 방식 | 앵커 | 좌상단(mm) | 폭(mm) |")
    _out("| --- | --- | --- | --- | --- | --- |")
    for r in st.placed:
        _out(f"| {r.image} | {r.near} | {r.mode} | `{r.where}` | ({r.x_mm}, {r.y_mm}) | {r.w_mm} |")
    errs = check_structure(out)
    rep = diff(a.file, out)
    outside = check_scope(rep, sorted(st.allowed))
    _out("")
    _out("구조 검증: " + ("통과" if not errs else "실패 " + "; ".join(errs)))
    _out(f"변경 범위: 변경 노드 {len(rep.changes)}건, 추가 파일 {len(rep.added)}건, 지정 위치 밖 변경 {len(outside)}건 → " + ("통과" if not outside else "실패"))
    for c in outside:
        _out(f"  - {c.part} {c.locpath or c.xpath}: {c.what}")
    if not a.pdf:
        _out("참고: 추정 방식 배치입니다. 한글 화면 또는 PDF 로 위치를 확인하십시오.")
    return 0 if not errs and not outside else 1


def cmd_render_copy(a) -> int:
    """PDF 실측용 사본: 인쇄 설정의 모아찍기(여러 쪽을 한 장에)를 해제한다. 제출 파일에는 쓰지 않는다."""
    pkg = HwpxPackage.open(a.file)
    changed = []
    for n in pkg.names():
        if not n.lower().endswith("settings.xml"):
            continue
        for el in pkg.xml(n).getroot().iter():
            if el.get("name") == "PrintMethod" and (el.text or "").strip() not in ("", "0"):
                changed.append(f"{n}: PrintMethod {el.text} → 0")
                el.text = "0"
                pkg.touch(n)
    out = a.output or a.file.replace(".hwpx", "_render.hwpx")
    pkg.save(out)
    print(f"결과: {out}")
    print("\n".join(changed) if changed else "모아찍기 설정 없음(그대로 복사)")
    return 0


def cmd_extract(a) -> int:
    from .extract import extract
    md, st = extract(a.file, a.tables, a.headers)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(md)
        _out(f"결과: {a.output}  (" + ", ".join(f"{k} {v}" for k, v in st.items()) + ")")
    else:
        sys.stdout.write(md)
    return 0


def _load_metrics(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_probe(a) -> int:
    """기호 폭 실측: (1) make — 측정 문단을 넣은 사본 생성 → 한글로 PDF 변환, (2) read — PDF 에서 폭을 읽어 JSON 저장."""
    from .outline import make_probe, read_probe
    if a.action == "make":
        pkg = HwpxPackage.open(a.file)
        from .locate import Locator
        n = make_probe(pkg, Locator(pkg), a.like)
        out = a.output or a.file.replace(".hwpx", "_probe.hwpx")
        pkg.save(out)
        _out(f"결과: {out}  (측정 문단 {n}개, 한글로 PDF 변환 후 'probe read <PDF>' 실행)")
    else:
        m = read_probe(a.file)
        out = a.output or "metrics.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=1)
        _out(f"결과: {out}")
        for k, v in m.items():
            _out(f"- {k!r}: {v} HWPUNIT ({v / 7200 * 25.4:.2f}mm)")
    return 0


def cmd_write(a) -> int:
    from .outline import OutlineError, apply, parse
    with open(a.body, encoding="utf-8") as fh:
        items = parse(fh.read())
    if not items:
        _out("본문이 비어 있음")
        return 1
    pkg = HwpxPackage.open(a.file)
    from .locate import Locator
    loc = Locator(pkg)
    try:
        r = apply(pkg, loc, items, a.style, at=a.at, after=a.after, replace=a.replace, to=a.to, nth=a.nth,
                  consume_empty=a.consume_empty, like=a.like, end=a.end, indent_em=a.indent_em,
                  metrics=_load_metrics(a.metrics))
    except (OutlineError, LookupError) as e:
        _out(f"작성 실패 — 저장하지 않음: {e}")
        return 1
    out = a.output or _default_out(a.file)
    if os.path.abspath(out) == os.path.abspath(a.file):
        _out("원본 덮어쓰기는 허용하지 않음: -o 로 다른 파일명을 지정")
        return 1
    pkg.save(out)
    _out(f"결과: {out}")
    _out(f"- 문단 {r['inserted']}개 삽입, {r['removed']}개 대체 ({a.style}, 기준 문단: '{r['template']}')")
    errs = check_structure(out)
    rep = diff(a.file, out)
    outside = check_scope(rep, sorted(r["allowed"]))
    _out("구조 검증: " + ("통과" if not errs else "실패 " + "; ".join(errs)))
    _out(f"변경 범위: 변경 노드 {len(rep.changes)}건, 지정 위치 밖 변경 {len(outside)}건 → " + ("통과" if not outside else "실패"))
    for c in outside[:10]:
        _out(f"  - {c.part} {c.locpath or c.xpath}: {c.what}")
    return 0 if not errs and not outside else 1


def cmd_lint(a) -> int:
    from .lint import check, fix, report
    pkg = HwpxPackage.open(a.file)
    fs = check(pkg)
    _out(f"# 공문 규칙 검사: {os.path.basename(a.file)}")
    _out("")
    _out(report(fs))
    if not a.fix:
        return 0
    codes = {c.strip().upper() for c in a.fix.split(",") if c.strip()}
    done, allowed, skipped = fix(pkg, fs, codes)
    out = a.output or _default_out(a.file)
    if os.path.abspath(out) == os.path.abspath(a.file):
        _out("원본 덮어쓰기는 허용하지 않음: -o 로 다른 파일명을 지정")
        return 1
    pkg.save(out)
    _out("")
    _out(f"수정: {len(done)}건 ({', '.join(sorted(codes))}) → {out}")
    for sk in skipped:
        _out(f"  - 건너뜀: {sk}")
    errs = check_structure(out)
    rep = diff(a.file, out)
    outside = check_scope(rep, sorted(allowed))
    _out("구조 검증: " + ("통과" if not errs else "실패 " + "; ".join(errs)))
    _out(f"변경 범위: 변경 노드 {len(rep.changes)}건, 지정 위치 밖 변경 {len(outside)}건 → " + ("통과" if not outside else "실패"))
    return 0 if not errs and not outside else 1


def cmd_attach_align(a) -> int:
    from .lint import align_attachments
    pkg = HwpxPackage.open(a.file)
    notes = align_attachments(pkg, a.pdf)
    if not notes:
        _out("정렬할 붙임 목록(붙임 : 1. … 다음 줄 2. …)을 찾지 못함")
        return 1
    out = a.output or _default_out(a.file)
    pkg.save(out)
    _out(f"결과: {out}")
    for n in notes:
        _out("- " + n)
    errs = check_structure(out)
    rep = diff(a.file, out)
    allowed = sorted({c.locpath for c in rep.changes if c.locpath.startswith("s") and "/p[" in c.locpath})
    outside = check_scope(rep, allowed)
    _out("구조 검증: " + ("통과" if not errs else "실패 " + "; ".join(errs)))
    _out(f"변경 범위: 변경 노드 {len(rep.changes)}건 (붙임 문단·문단모양 추가만), 그 밖 변경 {len(outside)}건")
    return 0 if not errs and not outside else 1


def cmd_kind(a) -> int:
    from .package import file_kind
    rc = 0
    for f in a.files:
        k = file_kind(f)
        note = {"hwpx": "그대로 작업 가능", "hwp": "HWP(바이너리) → PC 한글로 HWPX 변환 후 작업 (windows/convert_hwp.ps1)",
                "zip": "ZIP 이지만 HWPX 아님", "other": "HWP/HWPX 아님"}[k]
        _out(f"{k}\t{os.path.basename(f)}\t{note}")
        rc = rc or (0 if k == "hwpx" else 2)
    return rc


def cmd_roundtrip(a) -> int:
    out = a.output or os.path.join(tempfile.mkdtemp(), "roundtrip_" + os.path.basename(a.file))
    pkg = HwpxPackage.open(a.file)
    if a.reserialize:  # 모든 XML 을 강제로 재직렬화해 직렬화기 자체를 시험
        for n in pkg.names():
            if n.endswith((".xml", ".hpf")):
                pkg.touch(n)
    pkg.save(out)
    errs = check_structure(out)
    rep = diff(a.file, out)
    ok = not errs and rep.identical
    _out(f"{'통과' if ok else '실패'}\t{os.path.basename(a.file)}\t구조오류 {len(errs)}\t변경 {len(rep.changes)}")
    for e in errs:
        _out("  - " + e)
    if not rep.identical:
        _out(format_diff(rep))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pehwpx", description=f"pe-hwpx {__version__}")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("scan"); p.add_argument("file"); p.add_argument("--cells", action="store_true"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_scan)
    p = sp.add_parser("locate"); p.add_argument("file"); p.add_argument("spec"); p.set_defaults(fn=cmd_locate)
    p = sp.add_parser("verify"); p.add_argument("original"); p.add_argument("result", nargs="?"); p.set_defaults(fn=cmd_verify)
    p = sp.add_parser("fill"); p.add_argument("file"); p.add_argument("map"); p.add_argument("--data"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_fill)
    p = sp.add_parser("set"); p.add_argument("file"); p.add_argument("spec"); p.add_argument("value", nargs="?"); p.add_argument("--after"); p.add_argument("--date"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_set)
    p = sp.add_parser("register"); p.add_argument("file"); p.add_argument("-o", "--output"); p.add_argument("--id"); p.add_argument("--title"); p.set_defaults(fn=cmd_register)
    p = sp.add_parser("match"); p.add_argument("file"); p.add_argument("--maps", nargs="*"); p.set_defaults(fn=cmd_match)
    p = sp.add_parser("make"); p.add_argument("file"); p.add_argument("--map"); p.add_argument("--maps", nargs="*"); p.add_argument("--set", action="append"); p.add_argument("--data"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_make)
    p = sp.add_parser("fields"); p.add_argument("map"); p.set_defaults(fn=cmd_fields)
    p = sp.add_parser("stamp"); p.add_argument("file"); p.add_argument("spec_file"); p.add_argument("--pdf"); p.add_argument("--assets"); p.add_argument("--seed", type=int); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_stamp)
    p = sp.add_parser("render-copy"); p.add_argument("file"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_render_copy)
    p = sp.add_parser("extract"); p.add_argument("file"); p.add_argument("-o", "--output"); p.add_argument("--tables", choices=["auto", "md", "html"], default="auto"); p.add_argument("--headers", action="store_true"); p.set_defaults(fn=cmd_extract)
    p = sp.add_parser("write"); p.add_argument("file"); p.add_argument("body"); p.add_argument("--style", choices=["report", "gonmun"], default="report")
    p.add_argument("--at"); p.add_argument("--after"); p.add_argument("--replace"); p.add_argument("--to"); p.add_argument("--nth", type=int, default=1)
    p.add_argument("--consume-empty", action="store_true"); p.add_argument("--like"); p.add_argument("--end", action="store_true")
    p.add_argument("--indent-em", type=float, default=1.0); p.add_argument("--metrics"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_write)
    p = sp.add_parser("probe"); p.add_argument("action", choices=["make", "read"]); p.add_argument("file"); p.add_argument("--like"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_probe)
    p = sp.add_parser("lint"); p.add_argument("file"); p.add_argument("--fix"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_lint)
    p = sp.add_parser("attach-align"); p.add_argument("file"); p.add_argument("--pdf"); p.add_argument("-o", "--output"); p.set_defaults(fn=cmd_attach_align)
    p = sp.add_parser("kind"); p.add_argument("files", nargs="+"); p.set_defaults(fn=cmd_kind)
    p = sp.add_parser("roundtrip"); p.add_argument("file"); p.add_argument("-o", "--output"); p.add_argument("--reserialize", action="store_true"); p.set_defaults(fn=cmd_roundtrip)
    a = ap.parse_args(argv)
    from .package import NotHwpxError
    try:
        return a.fn(a)
    except NotHwpxError as e:
        _out(str(e))
        return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # 출력이 head 등으로 잘린 경우
        sys.exit(0)
