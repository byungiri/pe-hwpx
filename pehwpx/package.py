"""HWPX 컨테이너 입출력.

원칙
- 수정하지 않은 ZIP 항목은 원본 바이트를 그대로 다시 쓴다(압축 방식·순서·시각 보존).
- 수정한 XML 항목만 직렬화하며, 원본 XML 선언부(prolog)를 그대로 붙인다.
- mimetype 항목은 항상 첫 번째, 비압축으로 둔다.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

from lxml import etree

from . import NS

MIMETYPE = b"application/hwp+zip"
_CR_MARK = "\ue000".encode("utf-8")  # 저장 시 CR 로 복원되는 보호 문자

_PARSER = etree.XMLParser(
    remove_blank_text=False,
    resolve_entities=False,
    strip_cdata=False,
    huge_tree=True,
)


@dataclass
class Entry:
    name: str
    data: bytes
    info: zipfile.ZipInfo
    tree: etree._ElementTree | None = None
    dirty: bool = False
    prolog: bytes = b""
    epilog: bytes = b""
    cr_guard: bool = False


class NotHwpxError(ValueError):
    pass


OLE_SIG = bytes.fromhex("D0CF11E0A1B11AE1")


def file_kind(path: str) -> str:
    """'hwpx' | 'hwp' | 'zip'(HWPX 아님) | 'other' — 확장자가 아니라 파일 내용으로 판별."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    if head == OLE_SIG:
        return "hwp"   # HWP 5.0 은 OLE 복합 문서(한글 97 이전 HWP 3.x 는 다른 서명이지만 한글로 변환 가능)
    if head[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(path) as zf:
                if "mimetype" in zf.namelist() and zf.read("mimetype").startswith(b"application/hwp+zip"):
                    return "hwpx"
                if any(n.startswith("Contents/section") for n in zf.namelist()):
                    return "hwpx"
        except zipfile.BadZipFile:
            return "other"
        return "zip"
    if head.startswith(b"HWP Document File"):
        return "hwp"   # HWP 3.x
    return "other"


@dataclass
class HwpxPackage:
    path: str
    entries: list[Entry] = field(default_factory=list)

    # ------------------------------------------------------------ 열기
    @classmethod
    def open(cls, path: str) -> "HwpxPackage":
        kind = file_kind(path)
        if kind == "hwp":
            raise NotHwpxError(
                f"{os.path.basename(path)}: HWP(한글 바이너리) 파일입니다. 사용자 PC 의 한글로 HWPX 로 변환한 뒤 작업하세요 — "
                "windows/convert_hwp.ps1 -Src <파일 또는 폴더> [-OutDir <폴더>] (SKILL.md 'HWP 파일 처리')")
        if kind != "hwpx":
            raise NotHwpxError(f"{os.path.basename(path)}: HWPX 파일이 아님 ({kind})")
        pkg = cls(path=path)
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                pkg.entries.append(Entry(info.filename, zf.read(info), info))
        return pkg

    # ------------------------------------------------------------ 조회
    def names(self) -> list[str]:
        return [e.name for e in self.entries]

    def entry(self, name: str) -> Entry:
        for e in self.entries:
            if e.name == name:
                return e
        raise KeyError(name)

    def has(self, name: str) -> bool:
        return any(e.name == name for e in self.entries)

    def xml(self, name: str) -> etree._ElementTree:
        """XML 항목을 파싱해 돌려준다(최초 1회 파싱 후 캐시)."""
        e = self.entry(name)
        if e.tree is None:
            raw = e.data
            # XML 파서는 CR LF 를 LF 로 정규화하므로, 원본의 CR 을 사용자 정의 영역 문자로
            # 보호했다가 저장 시 되돌린다(그림 설명 등 한글이 CRLF 로 기록한 텍스트 보존).
            if b"\r" in raw and _CR_MARK not in raw:
                raw = raw.replace(b"\r", _CR_MARK)
                e.cr_guard = True
            root = etree.fromstring(raw, _PARSER)
            e.prolog = _prolog_of(raw, root)
            end = raw.rstrip()
            e.epilog = raw[len(end):] if end.endswith(b">") else b""
            e.tree = etree.ElementTree(root)
        return e.tree

    def touch(self, name: str) -> None:
        """해당 XML 항목을 저장 시 재직렬화 대상으로 표시한다."""
        self.xml(name)
        self.entry(name).dirty = True

    def manifest_items(self) -> list[dict]:
        """Contents/content.hpf 의 opf:item 목록."""
        root = self.xml("Contents/content.hpf").getroot()
        items = []
        for it in root.iter("{%s}item" % NS["opf"]):
            items.append(dict(it.attrib))
        return items

    def section_names(self) -> list[str]:
        """본문 섹션 XML 경로를 spine 순서로 돌려준다."""
        root = self.xml("Contents/content.hpf").getroot()
        href = {i.get("id"): i.get("href") for i in root.iter("{%s}item" % NS["opf"])}
        out = []
        for ref in root.iter("{%s}itemref" % NS["opf"]):
            h = href.get(ref.get("idref"), "")
            if os.path.basename(h).startswith("section") and h.endswith(".xml"):
                out.append(h)
        if not out:  # spine 이 비어 있는 문서 대비
            out = sorted(
                (n for n in self.names() if n.startswith("Contents/section") and n.endswith(".xml")),
                key=lambda n: int("".join(ch for ch in n if ch.isdigit()) or 0),
            )
        return out

    def sections(self) -> list[etree._Element]:
        return [self.xml(n).getroot() for n in self.section_names()]

    # ------------------------------------------------------------ 바이너리
    def add_binary(self, filename: str, data: bytes, media_type: str, item_id: str) -> str:
        """BinData/ 에 파일을 추가하고 content.hpf 매니페스트에 등록한다. 반환: item id."""
        name = "BinData/" + filename
        if self.has(name):
            raise ValueError(f"이미 존재하는 바이너리: {name}")
        info = zipfile.ZipInfo(name, date_time=datetime.now().timetuple()[:6])
        info.compress_type = zipfile.ZIP_STORED if media_type in ("image/png", "image/jpeg", "image/gif") else zipfile.ZIP_DEFLATED
        # content.hpf 바로 앞(원본에서 BinData 가 놓이는 영역)에 끼워 넣는다.
        idx = next((i for i, e in enumerate(self.entries) if e.name.startswith("Contents/section")), len(self.entries))
        self.entries.insert(idx, Entry(name, data, info))
        hpf = self.xml("Contents/content.hpf").getroot()
        manifest = hpf.find("{%s}manifest" % NS["opf"])
        item = etree.SubElement(manifest, "{%s}item" % NS["opf"])
        item.set("id", item_id)
        item.set("href", name)
        item.set("media-type", media_type)
        item.set("isEmbeded", "1")
        self.touch("Contents/content.hpf")
        return item_id

    # ------------------------------------------------------------ 저장
    def save(self, out_path: str, backup: bool = True) -> str:
        """저장. out_path 가 원본과 같으면 먼저 .bak 백업을 만든다."""
        if backup and os.path.exists(out_path) and os.path.abspath(out_path) == os.path.abspath(self.path):
            shutil.copy2(out_path, out_path + ".bak")
        tmp = out_path + ".tmp"
        ordered = sorted(self.entries, key=lambda e: 0 if e.name == "mimetype" else 1)
        with zipfile.ZipFile(tmp, "w") as zf:
            for e in ordered:
                data = self._payload(e)
                info = zipfile.ZipInfo(e.name, date_time=e.info.date_time)
                info.compress_type = zipfile.ZIP_STORED if e.name == "mimetype" else e.info.compress_type
                info.external_attr = e.info.external_attr
                info.create_system = e.info.create_system
                zf.writestr(info, data)
        os.replace(tmp, out_path)
        return out_path

    def _payload(self, e: Entry) -> bytes:
        if e.name == "mimetype":
            return MIMETYPE if not e.data else e.data
        if not e.dirty or e.tree is None:
            return e.data
        body = etree.tostring(e.tree.getroot(), encoding="UTF-8", xml_declaration=False)
        out = e.prolog + body + e.epilog
        return out.replace(_CR_MARK, b"\r") if e.cr_guard else out


def _prolog_of(data: bytes, root: etree._Element) -> bytes:
    """루트 요소 앞의 모든 바이트(BOM, XML 선언, 공백, 주석)를 원본 그대로 돌려준다."""
    tag = (root.prefix + ":" if root.prefix else "") + etree.QName(root).localname
    pos = data.find(b"<" + tag.encode("utf-8"))
    return data[:pos] if pos > 0 else b""
