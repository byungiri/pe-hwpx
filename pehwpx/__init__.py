"""pe-hwpx: 기술사 업무 문서용 HWPX 처리 도구.

OWPML(KS X 6101) 공개 규격과 한글에서 저장한 실제 문서 분석을 근거로 독자 작성.
Copyright (c) 2026 기술법인 진성 (Jinseong Technical Corporation). MIT License.
"""

__version__ = "0.9.2"

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "opf": "http://www.idpf.org/2007/opf/",
}


def q(prefix: str, local: str) -> str:
    """Clark 표기 태그명: q('hp', 'p') -> '{...paragraph}p'."""
    return "{%s}%s" % (NS[prefix], local)
