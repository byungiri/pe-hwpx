# pe-hwpx

**한글(HWPX) 양식을 원본 서식 그대로 채우는 Claude 스킬** — 기술사 실무에서 검증

받은 한글 양식의 표·글자모양·쪽 배치를 건드리지 않고 필요한 칸만 채우고, 직인·서명을 넣고,
공문 작성 규칙을 검사합니다. 수정하지 않은 부분은 바이트 단위로 원본과 같게 저장하고,
저장할 때마다 지시한 위치 밖에 바뀐 곳이 없는지 스스로 검증합니다.
기술법인 진성이 기술사 업무(평가·자문위원 신청서, 감리·자문 보고서, 공문)에 쓰면서 다듬었습니다.

> **English summary** — A Claude skill for Korean Hancom Office HWPX documents. It fills official
> forms without disturbing the original layout (unchanged parts stay byte-identical), places seal,
> signature and check-mark images at measured positions, extracts text to Markdown, writes indented
> Korean report bodies, lints official letters against the Korean administrative rules, and converts
> HWP to HWPX via Hancom Office on Windows. Every save is verified against the original. MIT License.

## 누가 쓰면 좋은가

| 사용자 | 주로 쓰는 문서 | 도움이 되는 기능 |
| --- | --- | --- |
| 공무원·공공기관 실무자 | 공문(시행문), 보고서, 회의록 | 공문 규칙 검사(항목 기호·날짜·시각·금액 한글 병기·끝 표시), 개조식 본문 작성, 붙임 정렬 |
| 기술사·엔지니어링사 | 평가·자문위원 신청서, 감리·자문 의견서, 공정보고 | 양식 채우기, 경력·실적 반복행, 직인·서명 배치, 재직증명서 한 문장 작성 |
| 일반 사무 | 증명서, 동의서, 각종 신청서 | 빈칸 채우기, 날짜 채우기, 체크·서명 이미지 |
| 문서 검토자 | 과업지시서, 시방서, 받은 공문 | 텍스트 추출(표·메모·각주 유지), HWP → HWPX 변환 |

## 실무 적용 사례

| 사례 | 처리 내용 | 결과 |
| --- | --- | --- |
| 공공기관 평가위원 신청서 | 칸 채우기, 두 줄 칸 줄 간격 조정, 증명사진 칸 맞춤, 도장·서명 배치 | 원본 양식 그대로 1회 작성으로 제출 |
| 지자체 자문위원회 신청서(HWP) | HWP → HWPX 변환, 경력 행 추가, 타위원회 행 정리, 동의서 체크·서명 | 원본과 같은 4쪽 유지 |
| 준공검사 결과보고 공문 | 개조식 본문 작성, 붙임 번호 정렬 | 둘째 줄 정렬 오차 0.00mm(한글 PDF 실측) |
| 기술검토의견서·보고서 | 공문 규칙 검사 후 승인 항목만 자동 수정 | 날짜·금액 표기 일괄 정리 |
| 21쪽 설계 내역서 | 텍스트 추출, 규칙 검사 | 표 구조 유지, 검사 1초 이내 |

## 현재 상태: v0.9.2 (분석·채움·반복행·양식맵·이미지 배치·추출·개조식 작성·공문 검사·검증)

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | HWPX 입출력, 위치 지정(셀 좌표·라벨·누름틀), 양식 분석, 구조 검증·변경 범위 diff | 완료 |
| 2 | 채움(표 칸·문단 항목·날짜·누름틀·자리표시자), 채움 파일(JSON/YAML) | 완료 |
| 2 | 양식맵: 항목 이름 등록, 첨부 양식 자동 대조, 이름=값 작성 (내장: 재직증명서) | 완료 |
| 2 | 서명란 자리 채움(slot), 칸 폭 맞춤(fit), 견본 안내 글자색 해제, 빈칸 연도 날짜('20  .   .   .') | 완료 |
| 2 | 직인·서명·체크 이미지 배치 (한글 PDF 실측 좌표 / 추정), 역할 이름(@seal 등), 이미지 돌려쓰기·손 느낌 흔들림·배경 투명화 | 완료 |
| 2 | 이미지 준비: 서명·체크·도장 사진 → 배경 투명·하나씩 분리·assets.json 생성 (`assets make`, [docs/ASSETS.md](docs/ASSETS.md)) | 완료 |
| 2+ | 반복행(행 늘리기 grow·별지 annex·줄이기 trim, 세로 병합·순번 자동 조정) | 완료 |
| 3 | 텍스트 추출(마크다운, 표 구조·메모·각주·자동 번호 유지) | 완료 |
| 3 | 개조식 본문 작성(보고서 □○-·, 공문 1.가.1)가), 내어쓰기, 기호 폭 실측) | 완료 |
| 3 | 공문 규칙 검사(항목 기호·날짜·시각·금액·끝 표시·붙임, 승인 항목 자동 수정) | 완료 |
| 4 | HWP → HWPX 변환 후 작업(한글 COM, windows/convert_hwp.ps1), HWPX → HWP 역변환 | 완료 |
| 4 | Windows 한글 PDF 렌더 확인(windows/render_pdf.ps1), 공개 배포 | 완료 |

보존성 시험: 실제 업무 문서 6종(재직증명서, 공문, 신청서, 공정보고, 회의록, 이미지 포함 시방서)에서
강제 재직렬화 후에도 바이트 동일성을 확인했습니다. 지원 범위는 공문·신청서·증명서류·보고서 중심이며,
다른 양식은 Issues 로 알려 주시면 검토합니다.

## 설치

### claude.ai (웹·데스크톱 앱)

1. 오른쪽 **Releases** 에서 최신 `pe-hwpx-vX.Y.Z.zip` 을 내려받습니다. (초록색 Code → Download ZIP 은 폴더 이름이 달라 업로드되지 않습니다.)
2. Claude 설정 → 기능(Capabilities)에서 코드 실행·파일 생성을 켭니다.
3. 스킬 화면에서 「Skill 업로드」로 zip 을 올립니다. 새 버전이 나오면 같은 방법으로 올려 교체합니다.
4. 대화에 HWPX 양식을 첨부하고 "이 양식 분석해 줘"처럼 요청하면 스킬이 자동으로 쓰입니다.

### Claude Code

이 저장소를 `~/.claude/skills/pe-hwpx` 로 내려받고 `pip install lxml` 을 실행합니다.

## 필요 환경

| 기능 | 필요 환경 |
| --- | --- |
| 분석·채우기·반복행·양식맵·추출·개조식 작성·공문 검사·검증 | Claude 유료 요금제 + 코드 실행. 클라우드에서 동작(Python, lxml) |
| HWP → HWPX 변환, 한글 PDF 실측 배치·쪽 수 확인 | Windows PC + 한글(HWP) 설치 + Claude 데스크톱 앱의 PC 연결. `windows/` 의 PowerShell 스크립트 사용 |
| 직인·서명·체크 이미지 | 사용자 본인의 이미지 폴더와 `assets.json`(역할 정의). **준비 방법: [docs/ASSETS.md](docs/ASSETS.md)** — 종이에 쓴 서명·체크 사진을 올리면 자동 정리. 이미지는 스킬에 넣지 않습니다 |

## 개인정보

스킬에는 개인정보나 이미지가 들어 있지 않습니다. 성명·주소 등 고정 정보는 사용자가 대화에서 주거나 `--data` 자료 파일로 넣으며,
양식맵(`forms/`)에는 위치와 항목 이름만 저장합니다. 시험 문서는 저장소에 포함하지 않습니다.

## 오류 신고·개선 요청

Issues 에 남겨 주십시오. 실제 작성본 대신 **빈 양식**(개인정보 제거)과 증상, 사용한 명령을 함께 적어 주시면 재현이 빠릅니다.

## 사용 예

```bash
python -m pehwpx kind 받은파일.hwp          # hwp 이면 PC 에서 windows/convert_hwp.ps1 로 HWPX 변환
python -m pehwpx scan 신청서.hwpx
python -m pehwpx locate 신청서.hwpx "label:성명"
python -m pehwpx set 재직증명서.hwpx "s0/tbl[0]/r[6]/c[0]" --date today -o 결과.hwpx
python -m pehwpx fill 신청서.hwpx 채움.json --data 프로필.json -o 결과.hwpx
python -m pehwpx match 재직증명서.hwpx
python -m pehwpx make 재직증명서.hwpx --set "용도=○○ 제출용" -o 재직증명서_○○.hwpx
python -m pehwpx register 새양식.hwpx -o forms/새양식.json --id new-form --title 새양식
python -m pehwpx assets make 서명사진.jpg --role signature -o 도장폴더   # 이미지 준비(docs/ASSETS.md)
python -m pehwpx stamp 동의서.hwpx 배치.json --assets 도장폴더 --pdf 동의서.pdf -o 동의서_날인.hwpx
python -m pehwpx extract 과업지시서.hwpx -o 과업지시서.md
python -m pehwpx write 검토의견서.hwpx 의견.txt --style gonmun --replace "가. " --to "나. " -o 검토의견서_작성.hwpx
python -m pehwpx lint 시행문.hwpx
python -m pehwpx lint 시행문.hwpx --fix D1,T1,M1,E2 -o 시행문_수정.hwpx
python -m pehwpx render-copy 결과.hwpx -o 결과_render.hwpx   # 모아찍기 해제 실측용 사본
python -m pehwpx verify 원본.hwpx 결과.hwpx
python tests/gate1.py <HWPX 폴더>      # 보존성 자가 시험
python tests/gate2.py <HWPX 폴더>      # 채움 자가 시험
python tests/gate3.py <HWPX 폴더>      # 양식맵 자가 시험
python tests/gate4.py <HWPX 폴더>      # 이미지 배치 자가 시험
python tests/gate5.py <HWPX 폴더>      # 서명란·칸 맞춤·안내색·render-copy 자가 시험
python tests/gate6.py <HWPX 폴더>      # 반복행 자가 시험
python tests/gate7.py <HWPX 폴더>      # 텍스트 추출 자가 시험
python tests/gate8.py <HWPX 폴더>      # 개조식 본문 작성 자가 시험
python tests/gate9.py <HWPX 폴더>      # 공문 규칙 검사 자가 시험
python tests/gate10.py <HWPX 폴더>     # 반복행 병합 칸 높이·처리 순서, PDF 문구 찾기 회귀 시험
python tests/gate11.py                 # 이미지 준비(합성 사진) 시험
```

Claude에게는 "이 양식 분석해 줘", "재직증명서, ○○ 제출용으로 오늘 날짜 발급해 줘"처럼 요청하면 됩니다.
자주 쓰는 양식은 `register` 로 양식맵을 만들어 `forms/` 에 넣고 스킬을 다시 올리면 자동으로 인식됩니다.

## 면책 고지

본 스킬은 문서 작성 보조 도구이며, 생성 문서의 내용·법령 인용·제출 적정성에 대한 최종 확인과 책임은
작성자(기술사)에게 있습니다. 서명·직인 관련 기능은 사용자 본인의 자산으로 본인 명의 문서를 작성하는
경우에만 사용해야 하며, 타인 명의 문서 작성에 사용할 수 없습니다. 발주기관 양식의 저작권과 이용 조건은
각 기관의 방침을 따릅니다.

## 라이선스

MIT License. Copyright (c) 2026 기술법인 진성 (Jinseong Technical Corporation)
