# TAXiA·CLOA 및 AI 재무·세무·회계 자동 모니터링

이 저장소는 서로 분리된 두 개의 공개정보 모니터링 트랙을 운영합니다.

1. **AI 세무·법률 / TAXiA·CLOA 모니터링**  
   TAXiA·CLOA·XAIKOREA의 직접 변화와 국내외 세무·법률·AI 규제를 추적합니다.
2. **AI 재무·세무·회계 모니터링**  
   상용 서비스, 오픈소스, 논문·벤치마크, 공공 데이터·API, 법·제도·감사 변화를 별도 상태와 보고서로 추적합니다.

두 트랙 모두 공개 RSS·공식 API·공개 GitHub·PyPI·arXiv를 사용하며, 날짜별 Markdown/JSON 보고서와 GitHub 이슈를 발행합니다.

## 자동 실행

### AI 세무·법률 / TAXiA·CLOA

- 본 실행: **매일 오전 7:00, Asia/Seoul** (`0 22 * * *` UTC)
- 누락 감시: **오전 7:20**, 그날 성공 상태가 없을 때만 보조 실행
- 수동 실행: `Actions → Daily AI Tax Legal TAXiA CLOA Monitor → Run workflow`
- 보고서: `reports/YYYY/MM/YYYY-MM-DD.md`
- 이슈 라벨: `daily-monitoring`
- 실패 라벨: `monitor-failure`

### AI 재무·세무·회계

- 본 실행: **매일 오전 7:00, Asia/Seoul** (`0 22 * * *` UTC)
- 누락 감시: **오전 7:20**, 재무·세무·회계 전용 성공 상태가 없을 때만 보조 실행
- 수동 실행: `Actions → Daily AI Finance Tax Accounting Monitor → Run workflow`
- 보고서: `reports-finance-tax-ai/YYYY/MM/YYYY-MM-DD.md`
- 이슈 라벨: `finance-tax-ai-monitoring`
- 실패 라벨: `finance-tax-ai-monitor-failure`
- 진단파일: Actions artifact `finance-tax-ai-monitor-diagnostics-*`, 30일 보존

GitHub 예약 작업은 서비스 부하로 지연되거나 드물게 누락될 수 있습니다. 각 트랙은 독립된 상태 파일, concurrency group, 실패 이슈와 07:20 watchdog을 사용합니다.

## TAXiA·CLOA 집중 모니터링

다음 명칭과 공개 자산을 직접 확인합니다.

- `TAXiA`, `택시아`, `taxia-core`
- `CLOA 엔진`, `CLOA engine`
- `XAIKOREA`, `엑스에이아이코리아`
- `xaikorea/taxia` GitHub 저장소의 릴리스·커밋·이슈·PR·메타데이터
- PyPI `taxia-core` 릴리스
- Hugging Face `xaikorea0` 모델·데이터셋·Space
- TAXiA 공식 문서 페이지 변경
- 언론·검색 색인·외부 GitHub 언급

`CLOA`, `TAXiA`, `XAIKOREA`에는 동명·유사명 결과가 존재합니다. 세무·회계·XAIKOREA 문맥이 없는 개인비서·화장품·AI companion 등의 결과는 제외합니다.

기존 검색식은 [`config/sources.json`](config/sources.json)에서 관리합니다.

## AI 재무·세무·회계 모니터링 범위

재무 트랙은 단순 뉴스 검색이 아니라 다음 여섯 영역을 각각 분리해 보고합니다.

1. **TAXiA·CLOA 직접 관련**
2. **상용 서비스·기업 업데이트**
3. **오픈소스 프로젝트**
4. **논문·벤치마크**
5. **공공 데이터·API**
6. **법·제도·감사**

전용 검색·자산 목록은 [`config/finance_sources.json`](config/finance_sources.json)에서 관리합니다.

### 상용 서비스·기업

다음 업무군을 집중 확인합니다.

- 세법 리서치, 세무 에이전트, 신고·세무조정 자동화
- 기장, 거래 분류, 전표, 계정 조정, 월말결산
- 감사, 내부통제, 부정탐지, GRC
- FP&A, CFO 분석, 예산, 현금흐름, 재무예측
- AP·AR, 인보이스, 청구, 수금, 지급
- 세무·회계 MCP 서버와 범용 AI 커넥터
- 에이전트 권한, 인간 승인, 감사 추적, 비용 가시성

제품·기업 검색에는 Thomson Reuters, Blue J, Avalara, Wolters Kluwer, Canopy, TaxAct, Drake, Firm360, Intuit, QuickBooks, Xero, Sage, FloQast, Numeric, BlackLine, Vic.ai, Dext, Trullion, Workiva, Pleo, Billtrust, RecVue, Big Four 및 주요 회계법인 관련 변화가 포함됩니다.

### 오픈소스·패키지

고정 추적 저장소에는 다음이 포함됩니다.

- `xaikorea/taxia`
- `AI4Finance-Foundation/FinGPT`
- `AI4Finance-Foundation/FinRobot`
- `AI4Finance-Foundation/FinRL`, `FinRL-Trading`
- `OpenBB-finance/OpenBB`, `agents-for-openbb`
- `patronus-ai/financebench`
- `PolicyEngine/policyengine-core`
- `openfisca/openfisca-core`
- `frappe/erpnext`, `frappe/books`
- `docling-project/docling`
- `PaddlePaddle/PaddleOCR`

각 저장소의 메타데이터, 릴리스와 최근 커밋을 확인하며, TAXiA와 FinanceBench는 이슈·PR도 추적합니다. 별도로 GitHub Search API를 사용해 신규 세무 AI, 회계 에이전트, 금융 벤치마크, 인보이스 에이전트 저장소를 탐지합니다.

PyPI에서는 `taxia-core`, `openbb`, `policyengine-core`, `openfisca-core`, `docling`, `paddleocr`의 버전 변화를 추적합니다.

### 논문·벤치마크

arXiv 공식 Atom API에서 다음 검색군을 별도로 운영합니다.

- 금융 LLM·재무 에이전트
- 세법 추론·세무 벤치마크
- 회계 LLM·결산 에이전트
- 감사 LLM·감사 에이전트
- 재무 QA·수치 추론 벤치마크
- 인보이스·영수증 문서 AI

논문의 존재·제목·초록·업데이트 일시는 1차 메타데이터로 기록하지만, 논문에 기재된 성능 수치는 독립 검증으로 간주하지 않습니다.

### 공공 데이터·API

대한민국을 우선하며 다음 공식 데이터·개발 가이드 변경을 확인합니다.

- 국세청·국세법령정보시스템
- 기획재정부 세제·조세 자료
- 금융위원회·금융감독원
- OpenDART 개발가이드, 공시·재무·XBRL API
- 한국회계기준원 K-IFRS·회계기준
- 한국은행 ECOS
- 국가법령정보 공동활용 OPEN API
- 개인정보보호위원회

OpenDART와 국가법령정보 OPEN API 가이드는 정규화된 페이지 해시도 저장합니다. 변경 존재와 변경 의미를 구분해, 실제 내용은 원문 대조 대상으로 표시합니다.

### 해외 법·제도·감사

미국 IRS·Treasury·SEC·PCAOB·FASB·Federal Register, IFRS Foundation·EFRAG·ESMA, EU 조세총국, 영국 HMRC·FRC, 일본 국세청·금융청·회계기준위원회, 중국 세무·재정·증권당국, OECD를 공식 도메인 중심으로 확인합니다.

## 엄격한 관련성 필터

재무 트랙은 광범위한 `AI` 또는 `finance` 단어 하나만으로 항목을 통과시키지 않습니다.

- 검색군마다 **필수 맥락 그룹**을 설정합니다.
- 일반 제품·논문은 `AI 맥락`과 `재무·세무·회계 맥락`을 동시에 요구합니다.
- 공식기관 검색은 지정한 **공식 도메인 allowlist**를 함께 확인합니다.
- `AI companion`, 게임, 카지노, 화장품, 단순 주가예측 등 동명이의·비관련 결과를 제외합니다.
- 짧은 영문 키워드 `AI`, `MCP`, `VAT`, `LLM`은 단어 경계를 사용해 `said` 같은 오탐을 막습니다.
- 1차 출처, 기업 공식 발표, 뉴스 색인, 신규 저장소 발견의 신뢰도를 구분합니다.

엄격한 필터는 오탐을 줄이는 대신 경계 사례를 놓칠 수 있습니다. 따라서 8시간 중첩 조회와 07:20 watchdog을 함께 사용합니다.

## 우선순위와 보고서 필드

각 항목은 규칙 기반 점수로 `P0`~`P3`를 부여합니다.

- **P0:** 즉시 원문 검토가 필요한 공식 규정, 직접 제품 변경, 고영향 릴리스·위험 신호
- **P1:** 제품·아키텍처·공공 API·평가체계에 중요한 변화
- **P2:** 유의미하지만 긴급하지 않은 업데이트
- **P3:** 보존 가치가 있으나 우선 검토 필요성이 낮은 항목

상세 보고서는 각 항목에 다음을 기록합니다.

- 발표일 또는 업데이트일
- 관할과 업무 분류
- 출처 유형과 자동 신뢰도
- 상태와 수집 근거
- 검색·추적 경로
- TAXiA/CLOA 적용 시사점
- 원문 요약

공급업체가 제시한 정확도·생산성·ROI는 공급업체 주장으로 취급하며 독립 검증 여부를 별도로 확인해야 합니다.

## 신뢰성 장치

- 트랙별 독립 상태·보고서·이슈·실패 경보
- 8시간 중첩 조회로 검색·색인 지연 보완
- 180일 중복 제거 상태 보존
- 같은 날짜 재실행 시 기존 보고서와 병합
- 소스 하나의 장애가 전체 수집을 중단하지 않는 격리 구조
- 뉴스, GitHub 고정 추적, 논문 그룹이 모두 건강해야 성공 처리
- 성공 소스 수가 임계값보다 낮으면 워크플로 실패 처리
- 보고서·원시 JSON·상태를 저장소에 커밋해 감사 추적 유지
- diagnostics artifact 30일 보존
- 실패 이슈 자동 생성, 후속 성공 시 자동 댓글·종료
- 07:20 watchdog으로 기본 예약 누락 확인

## 로컬 검증

```bash
# 기존 세무·법률 트랙
python -m unittest discover -s tests -p 'test_monitor.py' -v
python monitor.py --dry-run --lookback-hours 48

# 재무·세무·회계 AI 트랙
python -m unittest discover -s tests -p 'test_finance_monitor.py' -v
python -m json.tool config/finance_sources.json >/dev/null
python finance_monitor.py --dry-run --lookback-hours 48
```

실제 수집에는 네트워크가 필요합니다. 별도 유료 검색 API나 LLM API 키는 필수 아닙니다. GitHub Actions에서는 저장소 기본 `GITHUB_TOKEN`으로 공개 GitHub API 호출 한도를 보완합니다.

## 공개 범위와 한계

이 저장소와 자동 이슈·보고서는 **공개**됩니다. 고객명, 계약서, 내부 전략, 계좌·급여·세금 신고자료, 비공개 감사자료를 입력하지 마십시오.

이 시스템이 수집할 수 없는 주요 범위는 다음과 같습니다.

- 유료 세무·법률·회계 데이터베이스
- 로그인·구독 전용 자료
- 검색엔진에 아직 색인되지 않은 문서
- 자동 접근을 차단한 사이트
- 이미지·스캔 PDF만 제공되는 자료
- 삭제·수정되어 공개 이력이 남지 않은 자료
- 고객사 내부 문서와 비공개 제품 로드맵

자동 분류와 시사점은 1차 선별입니다. 개별 사안의 법적 효력, 회계기준 적용, 세무 신고, 시행일, 귀속연도와 예외는 반드시 1차 자료와 전문가 검토로 확정해야 합니다.
