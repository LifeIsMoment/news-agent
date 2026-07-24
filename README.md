# AI 재무·세무·회계 및 TAXiA·CLOA 공개정보 모니터링

이 저장소는 두 개의 독립적인 공개정보 모니터링 트랙을 운영합니다.

1. **AI 재무·세무·회계 핵심 동향 모니터링**  
   상용 서비스, 공식기관, 논문·벤치마크, 공공 데이터·API, 법·제도, 감사, 오픈소스의 실질적 변화를 우선 추적합니다.
2. **AI 세무·법률 / TAXiA·CLOA 모니터링**  
   특정 프로젝트와 세무·법률·AI 규제 변화를 별도 트랙으로 보존합니다.

재무·세무·회계 핵심 동향 보고서에서 TAXiA·CLOA 직접 활동은 더 이상 핵심 우선순위가 아닙니다. 해당 내용은 작은 참고 부록으로만 남고, 시장·연구·기관·데이터·법제도 신호가 우선합니다.

## 자동 실행 일정

### AI 세무·법률 / TAXiA·CLOA

- 본 실행: 매일 **07:00 KST**
- 누락 감시: 매일 **07:20 KST**
- 보고서: `reports/YYYY/MM/YYYY-MM-DD.md`
- 일일 이슈 라벨: `daily-monitoring`
- 실패 라벨: `monitor-failure`

### AI 재무·세무·회계 핵심 동향

- 본 실행: 매일 **07:30 KST** (`30 22 * * *` UTC)
- 누락 감시: 매일 **07:50 KST** (`50 22 * * *` UTC)
- 보고서: `reports-finance-tax-ai/YYYY/MM/YYYY-MM-DD.md`
- 원시 JSON: `reports-finance-tax-ai/YYYY/MM/YYYY-MM-DD.json`
- 일일 이슈 라벨: `finance-tax-ai-monitoring`
- 실패 라벨: `finance-tax-ai-monitor-failure`
- 진단 Artifact: `finance-tax-ai-monitor-diagnostics-*`, 30일 보존

### 자동 품질분석·개선

- 실행: 매일 **08:20 KST** (`20 23 * * *` UTC)
- 품질 보고서: `quality-reports-finance-tax-ai/YYYY/MM/YYYY-MM-DD.md`
- 품질 이슈 라벨: `finance-monitor-quality`
- 자동개선 PR 라벨: `auto-improvement`
- 품질 실패 라벨: `finance-monitor-quality-failure`

## 핵심 모니터링 범위

### 1. 상용 서비스·기업 업데이트

- 세법 리서치, 세무 에이전트, 신고·세무조정 자동화
- 기장, 거래 분류, 전표, 원장, 조정, 월말결산
- 감사, 내부통제, 부정탐지, GRC
- FP&A, CFO 분석, 예산, 현금흐름, 재무예측
- AP·AR, 인보이스, 청구, 수금, 지급
- 재무·세무·회계 MCP 서버와 범용 AI 커넥터
- 에이전트 권한, 인간 승인, 감사 추적, 비용 가시성

Thomson Reuters, Blue J, Avalara, Wolters Kluwer, Canopy, TaxAct, Drake, Firm360, Intuit, QuickBooks, Xero, Sage, FloQast, Numeric, BlackLine, Vic.ai, Dext, Trullion, Workiva, Pleo, Billtrust, RecVue, Big Four 및 주요 회계법인 관련 변화를 확인합니다.

### 2. 논문·벤치마크·데이터셋

arXiv와 공개 저장소에서 다음 검색군을 분리 운영합니다.

- 금융 LLM과 재무 에이전트
- 세법 추론과 세무 벤치마크
- 회계 LLM과 결산 에이전트
- 감사 LLM, 내부통제, 부정탐지
- 재무 QA와 수치 추론 벤치마크
- 인보이스·영수증·문서 AI

논문의 존재와 메타데이터는 1차 출처로 기록하지만, 논문에 기재된 성능은 독립 검증 결과로 간주하지 않습니다. 데이터 공개성, 평가셋 누수, 재현성, 후속 검증 여부를 별도로 확인합니다.

### 3. 공식기관·공공 데이터·API

대한민국에서는 다음 출처를 우선 확인합니다.

- 국세청·국세법령정보시스템
- 기획재정부 세제·조세 자료
- 금융위원회·금융감독원
- OpenDART, 공시·재무·XBRL API
- 한국회계기준원
- 한국은행 ECOS
- 국가법령정보 공동활용 OPEN API
- 개인정보보호위원회

해외에서는 IRS, Treasury, SEC, PCAOB, FASB, Federal Register, IFRS Foundation, EFRAG, ESMA, EU 조세총국, HMRC, FRC, OECD, 일본·중국 관련 당국을 공식 도메인 중심으로 확인합니다.

### 4. 오픈소스·프로젝트·패키지

주요 고정 추적 대상은 다음과 같습니다.

- FinGPT, FinRobot, FinRL
- OpenBB와 관련 에이전트
- FinanceBench
- PolicyEngine, OpenFisca
- ERPNext, Frappe Books
- Docling, PaddleOCR
- 신규 세무 AI, 회계 에이전트, 금융 벤치마크, 인보이스 에이전트 저장소

오픈소스는 별 개수보다 라이선스, 최근 유지보수, 보안, 테스트, 재현성, 데이터 반출 구조를 우선 평가합니다.

## 핵심 우선순위 정책

각 항목은 `P0`~`P3`로 분류됩니다.

- **P0:** 즉시 원문 검토가 필요한 공식 규정·감리·제재·고영향 위험 신호
- **P1:** 제품, 연구, 벤치마크, 공공 API, 회계·세무 운영 구조에 중요한 변화
- **P2:** 유의미하지만 긴급하지 않은 업데이트
- **P3:** 근거 보존 가치는 있으나 우선 검토 필요성이 낮은 항목

다음 항목은 핵심 목록에서 자동 강등됩니다.

- 특정 프로젝트의 일반 커밋·문서 스타일 변경
- 최초 기준선 등록
- README·chore·버전 범프 등 기능 의미가 약한 커밋
- RSS만 존재하고 원문이 불명확한 항목
- 채용·모집·입찰·행사 등 도메인 변화와 직접 관련 없는 결과

기업 공식 발표는 최대 P1로 제한하며, 정확도·생산성·ROI는 공급업체 주장으로 표시합니다. 공식기관과 논문은 출처 신뢰도가 높더라도 시행일·적용범위·재현성은 별도 검증합니다.

## 자동 품질평가와 개선 루프

매일 생성된 보고서와 최근 GitHub Actions 실행을 분석해 다음 지표를 계산합니다.

- 상위 20개 핵심 순도
- 공식기관·논문·기업 공식·오픈소스 근거 비율
- 특정 프로젝트·기준선·노이즈 비율
- P0·P1 핵심 항목 수
- 세무·회계·감사·재무·문서 AI·공공 API 카테고리 커버리지
- 수집 소스 건강도
- Actions 성공률, 평균 실행시간, timeout 횟수

자동으로 변경할 수 있는 범위는 제한되어 있습니다.

- `min_report_score`, `max_report_items`, `max_issue_items`
- 수집 worker 수
- 반복 오탐에 대한 사전 승인된 제외어
- 특정 프로젝트의 부록 처리와 점수 상한
- 반복 timeout 발생 시 워크플로 `timeout-minutes` 상향

변경은 자동 브랜치와 PR로 생성되고, Python 구문·JSON·전체 `test_finance*.py` 테스트를 통과해야 합니다. 변경 파일과 변경 개수가 정책 범위 안이면 자동 병합을 시도하고, 보호 규칙이나 검사에서 차단되면 PR을 열어 둡니다.

자동 병합하지 않는 범위는 다음과 같습니다.

- 임의 수집기 알고리즘 생성
- 공식 출처 삭제
- 법적·회계적 판단 규칙 변경
- 보안·권한 정책 완화
- 테스트 우회
- 광범위한 GitHub Actions 재작성

정책은 `config/finance_quality_policy.json`, 분석기는 `finance_monitor_quality.py`, 실행 워크플로는 `.github/workflows/daily-finance-monitor-quality.yml`에서 관리합니다.

## 보고서 필드

각 핵심 항목에는 다음 정보가 포함됩니다.

- 발표일 또는 업데이트일
- 업무 영역과 관할
- 출처 유형과 신뢰도
- 상태와 수집 근거
- 핵심 시사점
- 검증 포인트
- 검색·추적 경로
- 원문 요약

## 신뢰성 장치

- 트랙별 독립 상태·보고서·이슈·실패 경보
- 8시간 중첩 조회와 180일 중복 제거
- 같은 날짜 재실행 시 기존 보고서 병합
- 소스별 장애 격리
- 핵심 소스 그룹 건강도 검사
- 보고서·원시 JSON·품질지표·상태의 Git 감사 추적
- 07:50 누락 감시
- 실패 이슈 자동 생성과 후속 성공 시 자동 종료
- PR 기반 제한형 자동개선

## 로컬 검증

```bash
# 기존 세무·법률 트랙
python -m unittest discover -s tests -p 'test_monitor.py' -v

# 재무·세무·회계 핵심 모니터와 품질개선
python -m py_compile finance_monitor.py finance_monitor_entry.py finance_monitor_quality.py
python -m json.tool config/finance_sources.json >/dev/null
python -m json.tool config/finance_quality_policy.json >/dev/null
python -m unittest discover -s tests -p 'test_finance*.py' -v
```

## 공개 범위와 한계

이 저장소와 자동 이슈·보고서는 공개됩니다. 고객명, 계약서, 내부 전략, 계좌·급여·신고자료, 비공개 감사자료를 입력하지 마십시오.

유료 데이터베이스, 로그인 전용 자료, 검색 미색인 문서, 자동 접근 차단 사이트, 이미지·스캔 PDF만 제공되는 자료, 비공개 제품 로드맵은 누락될 수 있습니다. 자동 분류와 시사점은 탐지용 1차 선별이며, 회계기준 적용·세무 신고·법적 효력·시행일·귀속연도·예외는 1차 자료와 전문가 검토로 확정해야 합니다.
