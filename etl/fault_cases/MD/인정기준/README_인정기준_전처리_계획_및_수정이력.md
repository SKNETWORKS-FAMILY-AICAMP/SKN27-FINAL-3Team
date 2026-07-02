# 기준정보 PDF 전처리 계획 및 수정 이력

## 1. 문서 목적

이 문서는 `etl/fault_cases` 프로젝트의 현재 폴더 구조를 기준으로, 과실비율 기준정보 PDF 전처리를 어떤 흐름으로 설계했는지, 각 Python 파일이 어떤 역할을 하는지, 그리고 전처리 결과 점검 후 어떤 문제를 어떤 근거로 수정했는지 정리한 문서이다.

이전 버전 문서는 다른 프로젝트 구조를 기준으로 작성되어 있었기 때문에, 현재 기준은 아래 경로를 기준으로 한다.

```text
etl/fault_cases/
├─ config/
│  └─ crawling_settings.json
├─ artifacts/
│  └─ fault_standard_output/
│     ├─ crawled/
│     │  ├─ collection_manifest.jsonl
│     │  ├─ collection_quality_report.jsonl
│     │  └─ raw_source_files/
│     └─ preprocessed/
└─ src/
   └─ fault_standard/
      ├─ config.py
      ├─ paths.py
      ├─ models.py
      ├─ crawling/
      └─ preprocessing/
```

## 2. 전체 처리 목표

이 파이프라인의 목표는 KNIA 과실비율 기준 PDF를 단순 텍스트 파일로 저장하는 것이 아니라, 이후 Neo4j 또는 RAG 검색에 바로 연결할 수 있는 구조화 데이터로 변환하는 것이다.

전처리 결과는 크게 다음 정보를 만든다.

```text
1. 기준서 단위 메타데이터
2. 개별 rule JSON
3. DB 적재용 JSONL table
4. party / base_fault / adjustment_factor / law_ref / reference_case
5. 사고유형 context
6. 검색용 chunk
7. parse_quality_report
```

이렇게 나눈 이유는 단순히 PDF 원문을 검색하는 방식으로는 “사고유형 매칭”, “기본과실 계산”, “수정요소 적용”, “법규/판례 근거 연결”을 안정적으로 하기 어렵기 때문이다.

예를 들어 사용자가 “신호 없는 사거리에서 좌회전 차량과 맞은편 우회전 차량 사고”라고 입력하면, 그래프에서는 다음 정보를 따로 찾을 수 있어야 한다.

```text
사고유형 = 교차로 사고
당사자 A/B = 좌회전 차량 / 우회전 차량
기본과실 = A:B
수정요소 = 특정 party에게 +5/-10
관련 법규 = 도로교통법 조항
판례/심의사례 = 근거 노드
```

따라서 전처리는 “PDF 텍스트 추출”보다 “계산 가능한 기준정보 구조화”가 핵심이다.

## 3. 실행 흐름

### 3.1 PDF 수집

수집 실행 파일은 다음이다.

```powershell
python -m etl.fault_cases.src.fault_standard.crawling.run_collection --headed --validate
```

수집 결과는 다음 위치에 저장된다.

```text
etl/fault_cases/artifacts/fault_standard_output/crawled/
├─ raw_source_files/
├─ collection_manifest.jsonl
└─ collection_quality_report.jsonl
```

현재 수집 대상 PDF는 다음 네 종류다.

```text
2023 공식 자동차사고 과실비율 인정기준
2020 비정형 사고 과실비율 기준
2021 PM 대 자동차 사고 과실비율 비정형 기준
2025 2차로형 회전교차로 사고 과실비율 비정형 기준
```

### 3.2 PDF 전처리

전체 전처리 실행 파일은 다음이다.

```powershell
python -m etl.fault_cases.src.fault_standard.preprocessing.run_all
```

개별 기준서별 전처리 모듈은 다음 네 개다.

```text
official_2023  : 2023 공식 인정기준
nontypical     : 2020 비정형 기준
pm_auto        : 2021 PM 대 자동차 기준
roundabout     : 2025 2차로형 회전교차로 기준
```

전처리 결과는 다음 위치에 저장된다.

```text
etl/fault_cases/artifacts/fault_standard_output/preprocessed/
├─ 2023_official_auto_accident_rulebook/
├─ 2020_nontypical_accident_rulebook/
├─ 2021_pm_vs_auto_nontypical_rulebook/
└─ 2025_two_lane_roundabout_rulebook/
```

## 4. 공통 Python 파일 역할

### `src/fault_standard/config.py`

프로젝트 공통 설정 진입점이다.

주요 역할은 다음과 같다.

```text
fault_cases 루트 계산
artifacts 경로 계산
crawled/raw_source_files 경로 계산
preprocessed 출력 경로 계산
config/crawling_settings.json 로딩
```

이 파일을 둔 이유는 크롤링과 전처리 모듈이 같은 경로 기준을 공유해야 하기 때문이다. 이전 프로젝트에서는 각 모듈이 자기 기준 경로를 들고 있었기 때문에 폴더 구조가 바뀌면 전부 깨질 위험이 있었다.

### `src/fault_standard/paths.py`

경로 관련 보조 함수 또는 경로 객체를 관리하는 파일이다.

전처리/수집 단계에서 상대경로를 직접 하드코딩하지 않고, 프로젝트 루트 기준으로 계산하도록 하기 위한 용도다.

### `src/fault_standard/models.py`

공통 데이터 모델을 둘 수 있는 파일이다.

각 기준서별 전처리에도 `models.py`가 따로 있지만, 공통 모델이 필요한 경우 이 파일을 기준으로 확장할 수 있다.

## 5. Crawling 폴더 역할

경로:

```text
etl/fault_cases/src/fault_standard/crawling/
```

### `run_collection.py`

크롤링 실행 진입점이다.

사용자가 직접 실행하는 파일이며, 다음 일을 한다.

```text
1. crawling_settings.json 로드
2. Playwright Chromium 설치 여부 확인
3. KNIA 기준정보 게시판 접근
4. PDF 후보 수집
5. 후보 점수화
6. PDF 다운로드
7. manifest / quality report 생성
```

Playwright 브라우저가 설치되지 않은 경우 `setup_browser.py`를 통해 자동 설치를 시도하도록 수정되어 있다. 그 이유는 `requirements.txt`는 Python 패키지만 설치하고, Playwright Chromium 실행 파일은 별도 설치가 필요하기 때문이다.

### `crawler.py`

실제 사이트 탐색과 게시글 후보 수집의 중심 로직이다.

KNIA 기준정보 페이지의 게시글 목록을 읽고, PDF가 붙어 있는 게시글을 찾는다. 이때 단순히 파일명만 보지 않고 게시글 제목과 첨부파일 정보를 함께 본다.

### `candidate_scorer.py`

게시글 후보 중 어떤 PDF가 목표 문서인지 판별하는 점수화 로직이다.

하드코딩된 파일명만 의존하지 않고, 다음 단서를 함께 사용한다.

```text
게시글 제목
첨부파일명
등록일
문서 유형 키워드
```

이 방식을 쓴 이유는 KNIA 사이트의 파일명이 바뀌거나 괄호/공백/연도 표기가 달라져도 수집 로직이 완전히 깨지지 않게 하기 위해서다.

### `browser_downloader.py`

Playwright 브라우저를 사용해 첨부파일을 다운로드한다.

직접 URL 다운로드가 막히거나 세션이 필요한 경우를 대비한 방식이다.

### `direct_downloader.py`

브라우저 없이 HTTP 요청으로 직접 다운로드할 수 있는 경우 사용하는 보조 다운로더다.

### `html_parser.py`

게시판 HTML에서 게시글, 첨부파일, 링크 정보를 파싱한다.

### `collection_validator.py`

수집 결과 품질을 검증한다.

예를 들어 기대한 문서 수가 맞는지, PDF 파일이 실제로 존재하는지, 파일 크기나 해시가 비어 있지 않은지 확인한다.

### `manifest.py`

수집된 파일의 메타데이터를 JSONL로 저장한다.

### `hash_utils.py`

PDF 파일 해시를 계산한다.

이 해시는 같은 파일인지, 다운로드가 바뀌었는지, 전처리 결과가 어떤 원본에서 나왔는지 추적하기 위한 근거다.

### `manual_register.py`

자동 수집이 어려운 파일을 수동 등록할 때 사용하는 보조 파일이다.

### `setup_browser.py`

Playwright Chromium 설치를 자동 처리한다.

`chromium==0.0.0` 같은 패키지를 설치하는 방식은 Playwright가 요구하는 브라우저 실행 파일을 해결하지 못하므로, 이 파일에서 `python -m playwright install chromium` 흐름을 담당한다.

## 6. Preprocessing 공통 구조

경로:

```text
etl/fault_cases/src/fault_standard/preprocessing/
```

### `run_all.py`

전체 전처리 실행 진입점이다.

다음 순서로 각 기준서를 처리한다.

```text
official_2023
nontypical
pm_auto
roundabout
```

기준서별 전처리 결과가 서로 독립적으로 생성되도록 모듈을 분리했다.

### 기준서별 공통 파일 구성

각 기준서 폴더는 대체로 다음 파일 구성을 가진다.

```text
main.py
config.py
pdf_loader.py
cleaners.py
rule_splitter.py
section_parser.py
extractors.py
classifiers.py
builder.py
chunker.py
file_utils.py
models.py
README.md
```

일부 기준서는 구조상 필요 없는 파일이 빠져 있거나, `summary_parser.py`, `classifiers_clean.py` 같은 보정 파일이 추가되어 있다.

### `main.py`

개별 기준서 전처리 실행 진입점이다.

공통 흐름은 다음과 같다.

```text
1. 경로 계산
2. 입력 PDF 찾기
3. PDF page text 로드
4. page coverage 생성
5. rule section 분리
6. rule JSON package 생성
7. 개별 rule JSON 저장
8. DB 적재용 JSONL 저장
9. manifest / summary 저장
```

### `config.py`

해당 기준서의 입력/출력 경로와 문서별 상수를 관리한다.

현재는 공통 `src/fault_standard/config.py`의 경로 함수를 사용하도록 맞춰져 있다.

이렇게 한 이유는 기준서별 config가 독립적으로 경로를 추측하면, 폴더 구조 변경 시 서로 다른 위치를 바라볼 수 있기 때문이다.

### `pdf_loader.py`

PDF를 페이지 단위 텍스트로 읽는다.

페이지 누락 여부, 전체 page count, loader report를 만들기 위한 기본 입력이다.

### `cleaners.py`

PDF 텍스트 추출 결과의 노이즈를 정리한다.

주요 처리:

```text
전각/반각 정규화
반복 공백 정리
제어문자 제거
헤더/푸터 제거
깨진 세로 라벨 복원
비율 표현 정규화
차로/방향 표현 정규화
```

제어문자 제거를 추가한 이유는 `\x07` 같은 문자가 party action이나 rule text에 남으면 movement, lane path, condition parser가 문장을 잘못 자르기 때문이다.

### `rule_splitter.py`

PDF 전체 텍스트에서 개별 rule section을 나누는 파일이다.

기준서마다 rule marker가 다르기 때문에 모듈별로 분리되어 있다.

예:

```text
2023 공식 기준: 보1, 차1-1, 거43-1
2020 비정형: No.1 ~ No.23
2021 PM: 도표01 ~ 도표38
2025 회전교차로: 회전-1 ~ 회전-15
```

rule boundary가 잘못 잡히면 뒤 rule, 목차, 다음 장 법규가 섞이므로 가장 중요한 단계 중 하나다.

### `section_parser.py`

본문 rule이 아닌 설명 section을 분리한다.

예:

```text
개요
적용범위
용어
수정요소 설명
올바른 통행방법
발간사/개정경과/총설
```

### `extractors.py`

rule 내부에서 실제 데이터 필드를 추출한다.

주요 추출 대상:

```text
parties
base_fault
variants / scenarios
adjustment_factors
law_refs
reference_cases
review_cases
usage_notes
lane_path_context
pm_context
vehicle_context
```

### `classifiers.py`

사고유형, 도로상황, 신호상황, 우선관계 등을 분류한다.

Neo4j 매칭에서 특히 중요한 값이다.

예:

```text
accident_group
accident_subgroup
collision_pattern
movement_relation
primary_violation
road_context
signal_context
```

### `builder.py`

추출된 정보들을 최종 rule JSON과 JSONL table로 조립한다.

`builder.py`는 전처리의 조립 공장 역할이다.

### `chunker.py`

검색/RAG용 chunk를 만든다.

rule 전체를 한 덩어리로 넣으면 검색 품질이 떨어지므로, 다음처럼 목적별 chunk를 나눈다.

```text
rule summary
base fault
adjustment explanation
law reference
case reference
context block
```

### `file_utils.py`

파일명 안전화, JSON/JSONL 저장, 해시 계산, 현재 시각 생성 같은 유틸리티를 담당한다.

Windows 경로 길이 문제 때문에 `safe_filename`은 길이를 제한하고, 긴 파일명에는 hash suffix를 붙이도록 수정했다.

## 7. 기준서별 전처리 설계와 수정사항

## 7.1 2020 비정형 기준

경로:

```text
etl/fault_cases/src/fault_standard/preprocessing/nontypical/
```

대상 문서:

```text
210107_2020년_비정형사고_과실비율_기준.pdf
```

### 설계 의도

2020 비정형 기준은 rule 수가 23개로 비교적 적지만, summary table과 detail rule이 따로 존재한다.

따라서 전처리 구조는 다음을 모두 보존하도록 설계했다.

```text
summary_table
detailed rule
parties A/B
base_fault
adjustment_factors
law_refs
review_cases
road_context
chunks
```

### 주요 문제

점검 결과 다음 문제가 있었다.

```text
summary table 행이 No.8/9, No.14/15에서 섞임
road_context가 일부 오분류됨
movement가 일부 None
review_case 과실비율 한쪽 누락
parse_quality_report가 너무 관대함
diagram은 아직 이미지 crop 단계가 아님
```

### 처리 방식과 이유

`summary_parser.py`는 다음 row 시작을 만나면 이전 row title에 붙이지 않도록 수정했다.

이유는 summary title이 섞이면 detail rule과 summary 대조가 불가능해지고, 나중에 Neo4j에서 rule title 검증에 실패하기 때문이다.

`classifiers.py`는 road context를 title/action 중심으로 재분류하도록 보강했다.

이유는 “점멸신호 교차로 사고”가 `횡단보도`로 들어가면 사용자의 사고 설명과 그래프 후보가 어긋나기 때문이다.

`extractors.py`는 movement vocabulary와 review_case ratio 정규식을 보강했다.

이유는 `우측 끼어들기`, `주차진행`, `횡단` 같은 표현이 빠지면 party 행동 정규화가 불완전해지고, 심의사례 그래프에서 과실비율 근거가 누락되기 때문이다.

diagram 관련 산출은 현재 이미지 crop 단계가 아니므로 Neo4j 적재 기준에서는 후순위로 두었다.

## 7.2 2021 PM 대 자동차 기준

경로:

```text
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/
```

대상 문서:

```text
!!210624_PM대자동차사고과실비율비정형기준_송부(2021).pdf
```

### 설계 의도

PM 기준은 A가 PM, B가 자동차인 방향성이 중요하다.

또한 같은 도표가 공통 해설/법규를 공유하거나, 하나의 도표 안에 여러 기본과실 시나리오가 존재한다.

따라서 일반 rule 구조 외에 다음 구조를 추가했다.

```text
pm_contexts
vehicle_contexts
signal_contexts
adjustment_condition_contexts
rule_scenarios
shared_rule_groups
shared_rule_group_members
shared_rule_group_blocks
shared_rule_group_law_refs
shared_rule_group_chunks
```

### 주요 문제

점검 결과 다음 문제가 있었다.

```text
adjustment_factors target_party_key/type 누락
road_context가 수정요소 조건에 오염됨
도표 01/02, 03/04, 06/07, 08/09, 33/34의 공통 해설/법규가 앞 도표에 안 붙음
도표 35/37/38 다중 기본과실 시나리오 누락
도표33 제목 오염
movement vocabulary 부족
parse_quality_report가 너무 약함
```

### 처리 방식과 이유

수정요소 target은 PM 기준의 기본 방향을 사용해 보완했다.

```text
A = PM
B = 자동차
```

예를 들어 `야간`, `시야장애`, `횡단금지`, `좌측통행`, `자전거도로`, `보도통행` 등은 PM/A 쪽 조건으로, `제동등`, `개문`, `문열림` 등은 자동차/B 쪽 조건으로 추론했다.

이유는 수정요소가 누구에게 적용되는지 모르면 계산 그래프에서 `AdjustmentFactor`를 연결할 수 없기 때문이다.

`road_context`와 `adjustment_condition_context`를 분리했다.

이유는 `인근에 자전거도로`, `좌측통행`, `야간` 같은 문구가 기본 사고상황이 아니라 수정요소 조건인데도 기본 도로상황에 섞이면, 사용자가 “신호위반 교차로 사고”를 물었을 때 “자전거도로 사고”로 매칭될 수 있기 때문이다.

공통 해설은 `SharedRuleGroup` 구조로 분리했다.

이유는 공통 해설/법규를 두 rule에 복사하면 중복 데이터가 많아지고, 반대로 한쪽에만 두면 앞 도표가 근거를 잃기 때문이다. group node 방식은 Neo4j에서 `HAS_MEMBER`, `HAS_SHARED_LAW`, `HAS_SHARED_EXPLANATION` 같은 관계로 표현하기 좋다.

도표 35/37/38은 `RuleScenario`로 분리했다.

이유는 하나의 rule에 `(가)/(나)/(다)` 기본과실이 함께 들어 있는 경우, 단일 `base_fault`만으로는 특정 시나리오 답변을 할 수 없기 때문이다.

도표33 제목은 `자동차 추돌 사고`, 도표34 제목은 `PM 추돌 사고`로 보정했다.

## 7.3 2025 2차로형 회전교차로 기준

경로:

```text
etl/fault_cases/src/fault_standard/preprocessing/roundabout/
```

대상 문서:

```text
250624_2차로형_회전교차로사고_과실비율_비정형기준.pdf
```

### 설계 의도

회전교차로 기준은 단순 A/B 과실보다 차로 경로가 중요하다.

그래서 `lane_paths.jsonl`을 핵심 table로 둔다.

중요 필드는 다음과 같다.

```text
red_path
blue_path
entry_direction
entry_lane
circulation_lane
exit_direction
exit_lane
lane_change_from
lane_change_to
conflict_lane
conflict_direction
role_in_rule
```

### 주요 문제

점검 결과 다음 문제가 있었다.

```text
회전-9~15 lane_path가 비어 있음
entry_direction / exit_direction이 같은 값으로 잘못 들어감
제어문자와 줄바꿈 때문에 party action이 잘림
conflict_direction이 모두 3시 방향으로 들어감
회전-2 conflict_lane 오분류
role_in_rule이 부정확함
reference_case에서 시간값을 과실비율로 잡음
diagram은 아직 이미지 crop 단계가 아님
```

### 처리 방식과 이유

party action parser를 한 줄 기준에서 다음 party/기본과실 marker 전까지 읽는 방식으로 바꿨다.

이유는 PDF 추출 결과에서 party action이 줄바꿈으로 끊기면 `차로변경`, `진출` 같은 핵심 단어가 누락되기 때문이다.

`entry_direction`과 `exit_direction`은 keyword별로 따로 추출하도록 수정했다.

이유는 기존 로직이 첫 방향만 잡아서 `entry_direction=12시`, `exit_direction=12시`처럼 같은 값으로 들어가는 문제가 있었기 때문이다.

`회전-12`, `회전-14`, `회전-15`처럼 실제 PDF 추출에서 문장 꼬리가 잘린 경우는 제한적으로 복원했다.

```text
회전-12 A: 2차로로 → 2차로로 차로변경
회전-14 B: 9시 → 9시 방향으로 회전
회전-15 A: 차로변경하여 → 차로변경하여 3시 방향으로 진출
```

이유는 이 문구들이 회전교차로 matching의 핵심 조건이고, 단순 parser 개선만으로는 이미 잘린 텍스트를 되살릴 수 없기 때문이다.

`conflict_direction`은 title/action/exit_direction을 기준으로 다시 계산하도록 수정했다.

회전-6, 회전-7은 12시 진출부, 회전-8은 9시 진출부로 보정했다.

`reference_case` 비율 파서에서는 `10:02`, `15:00` 같은 시간값을 과실비율에서 제외했다.

diagram 관련 산출은 제거했고, 다음 실행 시 오래된 `diagrams.jsonl`이 있으면 삭제하도록 했다.

## 7.4 2023 공식 인정기준

경로:

```text
etl/fault_cases/src/fault_standard/preprocessing/official_2023/
```

대상 문서:

```text
230630_자동차사고_과실비율_인정기준_최종.pdf
```

### 설계 의도

2023 공식 인정기준은 가장 큰 문서이며 rule 수가 많다.

기준 코드는 다음 prefix를 가진다.

```text
보: 자동차와 보행자 사고
차: 자동차와 자동차 사고
거: 자동차와 자전거/농기계 사고
```

따라서 rule code를 기준으로 section을 나눈 뒤, prefix에 따라 hierarchy와 accident_group을 분류한다.

### 주요 문제

점검 결과 다음 문제가 있었다.

```text
adjustment_factors target_party_key/type 대부분 null
factor_name empty 다수
variant scenario 일부 누락 또는 false variant 발생
비보행자 rule이 횡단보도로 오분류됨
보36, 차61-3 등 일부 rule boundary가 다음 장까지 번짐
law/reference context에 목차/다른 장 marker 포함
movement vocabulary 부족
제어문자 잔존
parse_quality_report가 너무 관대함
diagram은 아직 이미지 crop 단계가 아님
```

### 처리 방식과 이유

`classifiers_clean.py`를 새로 추가하고 `builder.py`가 이 파일을 사용하도록 변경했다.

기존 `classifiers.py`는 인코딩이 깨진 문자열이 많아 분류 기준으로 쓰기 위험했다. 파일 자체를 무리하게 고치기보다, 현재 프로젝트 기준의 정상 분류기를 별도 파일로 두는 방식이 안전하다고 판단했다.

수정요소는 줄 병합 방식으로 재파싱했다.

예전에는 다음과 같은 row가 생겼다.

```json
{
  "factor_name": "",
  "delta": 5,
  "raw_text": "+5"
}
```

이 문제를 해결하기 위해 `+5`, `-10`만 있는 줄은 직전 조건명 줄과 결합한다.

```text
어린이 보호구역
+5
```

위 텍스트는 다음처럼 처리된다.

```text
factor_name = 어린이 보호구역
delta = +5
condition_text = 어린이 보호구역
```

target party는 다음 기준으로 보완한다.

```text
보행자 rule에서 보 party가 있으면 보
차 party만 있으면 차
A/B rule이면 A를 기본 기준 party로 사용
```

이유는 공식 인정기준에서 수정요소가 특정 기준 당사자의 과실비율 증감으로 표기되는 경우가 많고, target이 null이면 계산 그래프에 연결할 수 없기 때문이다.

variant는 비율이 없는 `(가)/(나)` 표식만으로는 생성하지 않도록 수정했다.

이유는 단순 문단 번호가 scenario로 들어가면 `RuleScenario`가 false positive가 되고, 실제 계산 가능한 시나리오와 구분할 수 없기 때문이다.

법규/판례 context는 `목차`, `제2장`, `제3장`, 다음 rule marker를 만나면 자르도록 했다.

이유는 법규/판례 노드가 다른 장의 내용까지 먹으면 근거 그래프가 잘못 연결되기 때문이다.

rule boundary는 `rule_splitter.py`에서 다음 장/목차/변경대비표 marker를 만나면 잘라내도록 방어했다.

diagram 관련 산출은 제거했고, 다음 실행 시 오래된 `diagrams.jsonl`이 있으면 삭제하도록 했다.

## 8. Diagram을 제거한 이유

현재 단계에서 diagram은 이미지 전처리가 아니다.

기존 산출물의 diagram table은 다음처럼 비어 있었다.

```text
diagram_image_path = null
diagram_bbox = null
```

이 상태로 Neo4j에 넣으면 “그림이 있음”이라는 빈 메타 노드만 생기고, 실제 이미지 근거를 제공하지 못한다.

따라서 현재 전처리 단계에서는 diagram을 없는 것처럼 처리한다.

향후 이미지 crop 단계가 들어오면 그때 다음 정보를 갖춘 별도 파이프라인으로 추가하는 것이 맞다.

```text
diagram_id
rule_id
image_path
bbox
caption
visible_parties
visible_lanes
visible_signals
```

## 9. Parse Quality Report 강화 이유

기존 `parse_quality_report`는 대부분 `valid`로 나왔지만, 실제 데이터에는 다음 문제가 있었다.

```text
target_party_key null
movement None
road_context 오분류
lane_path empty
rule boundary 과다 span
law/reference context 오염
scenario 누락
title 오염
```

따라서 validator는 단순히 “rule 개수가 맞는가”가 아니라 “Neo4j 적재 가능한가”를 확인해야 한다.

현재 강화된 quality flag 예시는 다음과 같다.

```text
adjustment_target_party_missing
adjustment_target_party_type_missing
adjustment_factor_name_missing
movement_missing
lane_path_empty
direction_parse_suspicious
control_char_detected
rule_boundary_suspicious
evidence_context_contaminated
variant_ratio_missing
summary_title_mismatch
road_context_suspicious
shared_rule_group_attached
```

## 10. 파일명 길이 보정

Windows에서는 긴 경로에서 `FileNotFoundError`가 발생할 수 있다.

실제로 긴 한글 rule title이 포함된 JSON 파일 저장 시 문제가 발생했다.

따라서 각 기준서의 `file_utils.py`에서 `safe_filename`을 짧게 제한하고, 긴 이름에는 hash suffix를 붙이도록 수정했다.

예:

```text
원래 제목:
거10-2_후행직진자전거(미리우측끝으로다가섬)대선행우회전자동차.json

보정:
거10-2_후행직진자전거_해시.json
```

이 방식은 파일명을 사람이 어느 정도 알아볼 수 있게 유지하면서도 Windows 경로 제한을 피하기 위한 것이다.

## 11. 현재 산출물 주의사항

코드를 수정한 뒤 기존 산출물 파일이 자동으로 바뀌지는 않는다.

즉, 아래 위치의 JSON/JSONL은 전처리를 다시 실행해야 최신 로직이 반영된다.

```text
etl/fault_cases/artifacts/fault_standard_output/preprocessed/
```

특히 최근 수정된 항목은 다음 실행 후 확인해야 한다.

```text
PM shared_rule_groups 계열 table 생성
PM rule_scenarios 생성
PM adjustment_condition_contexts 생성
Roundabout diagrams.jsonl 제거
Official 2023 diagrams.jsonl 제거
Official 2023 classifiers_clean 반영
Official 2023 adjustment factor 재파싱
```

## 12. 현재 기준 실행 명령

전체 전처리:

```powershell
python -m etl.fault_cases.src.fault_standard.preprocessing.run_all
```

개별 전처리:

```powershell
python -m etl.fault_cases.src.fault_standard.preprocessing.official_2023.main
python -m etl.fault_cases.src.fault_standard.preprocessing.nontypical.main
python -m etl.fault_cases.src.fault_standard.preprocessing.pm_auto.main
python -m etl.fault_cases.src.fault_standard.preprocessing.roundabout.main
```

## 13. 향후 남은 작업

현재 수정은 텍스트 기반 전처리 품질을 Neo4j 적재에 가깝게 끌어올리는 작업이다.

다음 단계로 남은 작업은 다음과 같다.

```text
1. 수정 후 전처리 재실행
2. 기준서별 parse_quality_report 재점검
3. Neo4j node/relationship 설계와 table mapping 확정
4. diagram image crop 별도 파이프라인 설계
5. graph loader에서 shared_rule_group / rule_scenario / adjustment_condition_context 반영
6. 사용자의 사고 설명을 accident_group, party movement, context로 매칭하는 검색 계층 설계
```

가장 중요한 판단 기준은 “PDF에서 뭔가 뽑혔는가”가 아니라 “그래프에서 계산과 매칭에 쓸 수 있는가”이다.

그래서 이번 전처리 수정은 단순 추출량 증가보다 다음 원칙을 우선했다.

```text
target 없는 수정요소는 계산 불가
scenario 없는 다중 기준은 답변 불가
오염된 context는 잘못된 근거 연결
잘못된 accident_group은 후보 검색 실패
빈 diagram 메타는 현재 단계에서 의미 없음
```

## 14. 2020 비정형 기준 수정본 추가 보정

2020 비정형 기준은 1차 수정 후에도 Neo4j 최종 적재 전 보정할 항목이 남아 있었다.

수정본 점검 결과, 기본과실과 수정요소 계산에 필요한 핵심 데이터는 안정화되었지만 다음 문제가 확인되었다.

```text
rules: 23개 정상
parties: 46개 정상
base_faults: 23개 정상
adjustment_factors: 205개 정상
summary_table_rows: 23개 정상
movement 누락: 0건
adjustment target 누락: 0건
제어문자 잔존: 0건

남은 문제:
1. summary table 일부 row의 멀티라인 제목 오염
2. accident_group / road_area 일부 오분류
3. review_case 일부 과실비율 파싱 누락
4. image/diagram 산출물은 현재 텍스트 전처리 범위에서 제외 필요
```

이번 추가 보정은 “더 많이 추출하는 것”보다 “그래프에서 잘못 매칭되지 않게 하는 것”을 우선했다.

### 14.1 summary table 멀티라인 보정

PDF 요약표는 표 안의 제목이 여러 줄로 나뉘면서 다음 rule 제목 일부가 이전 row에 붙는 문제가 있었다.

특히 아래 row는 자동 줄 단위 파서만으로는 안정적으로 복구하기 어렵다.

```text
No.9  후행 우측 끼어들기 차량과 선행 우회전 대기차량간 사고
No.14 버스정류장에서 정차 후 출발 버스차량과 추월차량간 사고
No.15 동시 차로변경 사고
No.10 차량과 사고 / 차량 간 사고 표현 차이
```

따라서 `nontypical/summary_parser.py`에 `repair_known_summary_rows()`를 두었다.

이 함수는 PDF 추출 특성 때문에 반복적으로 깨지는 row만 canonical title로 보정한다.

이 방식을 사용한 이유는 다음과 같다.

```text
1. summary table은 rule 본문이 아니라 대조용 색인이다.
2. No.9/14/15는 PDF 줄바꿈 구조 때문에 일반 정규식만으로 안정 복구가 어렵다.
3. rule detail의 title/base_fault는 정상이라 summary row만 국소 보정하는 것이 안전하다.
4. 전체 파서 규칙을 과하게 바꾸면 정상 row까지 깨질 수 있다.
```

즉, 하드코딩으로 새 rule을 만드는 것이 아니라 이미 존재하는 23개 공식 row 중 PDF 멀티라인 추출 오류가 반복되는 row를 정규화하는 보정 단계다.

### 14.2 accident_group / road_area 제목 우선 분류

기존 분류는 제목과 본문 전체를 합쳐 키워드 순서대로 판단했다.

이 방식은 본문 해설이나 법규 문맥에 들어 있는 단어가 기본 사고상황을 덮어쓰는 문제가 있었다.

예를 들면 다음과 같다.

```text
No.2 적색점멸 직진 vs 황색점멸 직진
No.3 적색점멸 좌회전 vs 황색점멸 직진
No.4 적색점멸 직진 vs 황색점멸 좌회전

기대값: 교차로 / 점멸신호 계열
문제값: 횡단보도
```

또 다음 rule도 Neo4j 매칭 관점에서 위험했다.

```text
No.13 정차후 출발 vs 진로변경
No.14 버스정류장 사고
No.15 동시 차로변경
No.16 동일차로 진로변경
No.22 동일차로 내 우측 급진입 추월 이륜차
```

그래서 `nontypical/classifiers.py`의 기준을 바꾸었다.

```text
1. rule title을 기본 사고상황으로 우선 판단
2. 버스정류장, 점멸신호/교차로, 동일차로/진로변경/끼어들기/급진입을 먼저 분류
3. 본문 전체는 fallback으로만 사용
4. 횡단보도/주차장 같은 단어가 본문에 있어도 제목상 기본 사고상황을 덮지 못하게 처리
```

이렇게 한 이유는 Neo4j에서 `accident_group`과 `road_area`가 후보 검색의 시작점이기 때문이다.

예를 들어 사용자가 “적색점멸 차량과 황색점멸 차량 사고”라고 입력했는데 rule이 `횡단보도`로 들어가 있으면 후보 탐색 자체가 틀어진다.

따라서 사고유형 분류는 본문에 많이 등장한 단어보다 제목의 사고상황을 우선해야 한다.

### 14.3 review_case 과실비율 파싱 보강

심의결정사례에는 같은 의미라도 표현이 여러 가지로 나온다.

기존 정규식은 `과실`이라는 단어가 있어야 주로 잡혔다.

그래서 아래 문장이 누락될 수 있었다.

```text
청구차량 60%, 피청구차량 40%
```

이번에 `nontypical/extractors.py`의 `extract_claim_respondent_ratios()`를 보강했다.

보강 기준은 다음과 같다.

```text
청구차량 60%
청구차량 과실 60%
원고차량 60%
원고차량 과실 60%
피청구차량 40%
피청구차량 과실 40%
피고차량 40%
상대차량 40%
```

다만 한쪽 비율만 명시된 경우는 억지로 반대쪽 비율을 계산하지 않는다.

예를 들어 다음 문장은 partial 사례로 남기는 것이 맞다.

```text
청구차량 과실 30%는 적정
```

이 문장에서 피청구차량 70%를 임의 생성할 수도 있지만, 원문에 명시되지 않은 값을 만든 것이 되므로 근거 그래프에는 위험하다.

그래서 `claim_vehicle_fault_ratio = 30`, `respondent_vehicle_fault_ratio = null` 형태로 유지한다.

### 14.4 diagram/image 산출물 제외

현재 전처리의 목표는 텍스트 기반 Neo4j 적재 데이터다.

따라서 image crop, bbox, diagram image path, page image 같은 산출물은 이번 범위에서 제외한다.

이번 기준은 다음과 같다.

```text
생성하지 않음:
- diagrams.jsonl
- diagram_image_path
- diagram_bbox
- page image
- crop image

유지함:
- [도표해설] 안의 텍스트
- 사고상황 텍스트
- 기본과실 해설 텍스트
- 수정요소 해설 텍스트
- 관련법규 텍스트
- 심의결정사례 텍스트
```

여기서 중요한 점은 `[도표해설]`이라는 이름이 있어도 이미지가 아니라 PDF 본문에 적힌 텍스트 해설이라는 것이다.

그래서 `diagram_explanation` block은 이미지 산출물이 아니라 rule 설명 텍스트로 취급한다.

반대로 `diagrams.jsonl` 같은 이미지 메타 산출물은 현재 단계에서 필요 없으므로, `nontypical/main.py`에서 남아 있는 stale `diagrams.jsonl`이 있으면 다음 실행 때 삭제되도록 했다.

### 14.5 수정된 파일

이번 추가 보정에서 수정한 파일은 다음과 같다.

```text
etl/fault_cases/src/fault_standard/preprocessing/nontypical/summary_parser.py
- No.9, No.14, No.15 summary title canonical 보정
- No.10 표현 차이 보정
- summary raw text를 보정 title + ratio 중심으로 정리

etl/fault_cases/src/fault_standard/preprocessing/nontypical/classifiers.py
- accident_group을 title 우선으로 분류
- road_area를 title 우선으로 분류
- 점멸신호 교차로, 버스정류장, 동일차로/진로변경 계열 오분류 방지

etl/fault_cases/src/fault_standard/preprocessing/nontypical/extractors.py
- 청구/피청구 과실비율 정규식 보강
- "과실" 단어가 없는 "청구차량 60%, 피청구차량 40%" 패턴 지원
- 한쪽만 명시된 심의사례는 partial로 유지

etl/fault_cases/src/fault_standard/preprocessing/nontypical/main.py
- stale diagrams.jsonl 삭제
- 텍스트 전처리 범위 밖의 image/diagram table 산출물 방지
```

### 14.6 다음 실행 후 확인 기준

전처리를 다시 실행한 뒤에는 아래 기준으로 확인하면 된다.

```text
summary_table_rows:
- No.9 제목에 설명 문장 섞임 없음
- No.14 제목에 No.15 제목 섞임 없음
- No.15 제목 빈값 아님

rules / road_contexts:
- No.2/3/4 accident_group = 교차로 계열
- No.13 road_area = 동일차로 또는 진로변경 계열
- No.14 road_area = 버스정류장
- No.15 road_area = 동일차로 또는 진로변경 계열
- No.16 accident_group = 진로변경 계열
- No.22 accident_group / road_area = 동일차로 또는 진로변경/추월 계열

review_cases:
- "청구차량 60%, 피청구차량 40%" 패턴 양쪽 비율 추출
- 한쪽만 명시된 사례는 respondent null 유지

image/diagram:
- diagrams.jsonl 생성 안 됨
- stale diagrams.jsonl 있으면 삭제됨
```

## 15. 2021 PM 기준 수정본 추가 보정

2021 PM 대 자동차 기준은 1차 수정 후 구조가 크게 좋아졌다.

특히 A/B 방향, 수정요소 target, 다중 시나리오, 공유 해설 그룹은 이전보다 안정화되었다.

다만 수정본 점검 결과, Neo4j 최종 적재 전에 아래 문제가 남아 있었다.

```text
좋아진 부분:
- rules: 38개 정상
- parties: 76개 정상
- base_faults: 38개 정상
- adjustment_factors: 282개 정상
- rule_scenarios: 7개 추가
- shared_rule_groups: 5개 추가
- A=PM, B=자동차 방향 정상
- adjustment target_party_key/type 누락 0건
- 도표33 제목 오류 수정
- 도표35/37/38 다중 시나리오 추가
- 제어문자 잔존 0건

남은 문제:
1. road_context에 수정요소 조건이 아직 일부 섞임
2. shared_rule_group_chunks의 text/metadata가 null
3. rules/base_faults에서 다중 시나리오 사용 필요 여부가 명확하지 않음
4. diagrams.jsonl은 현재 텍스트 전처리 범위에서 제외 필요
```

이번 추가 보정의 핵심은 PM 기준에서 가장 위험한 오염을 제거하는 것이다.

PM 기준은 수정요소에 `인근 자전거도로`, `좌측통행`, `보도통행`, `야간`, `시야장애` 같은 조건이 자주 등장한다.

이 조건들은 사고의 기본 도로상황이 아니라 과실 가감 조건이다.

따라서 이 값들이 `road_contexts.jsonl`에 들어가면 사용자의 사고 설명을 잘못 매칭할 수 있다.

### 15.1 road_context 오염 제거

기존 문제 예시는 다음과 같았다.

```text
도표12 사거리 교차로(신호기 없음) 직진 대 좌회전 사고

문제:
road_area = 자전거도로
has_signal = true
has_bicycle_road = true
has_centerline = true

기대:
road_area = 교차로
has_signal = false
has_bicycle_road = false
```

이 문제는 기본 사고상황과 수정요소 조건이 같은 텍스트 안에서 함께 파싱되었기 때문에 생겼다.

그래서 `pm_auto/classifiers.py`에서 road context를 만들기 전에 수정요소성 문구를 제거하도록 했다.

제거 대상으로 본 표현은 다음과 같다.

```text
인근에 자전거도로가 있는 경우
인근에 자전거 도로가 있는 경우
대략 10m 이내
좌측통행
보도통행
보도 통행
야간
기타 시야장애
시야장애
횡단금지 표지
주택·상점가·학교
제동등 고장
```

이렇게 한 이유는 다음과 같다.

```text
base_road_context:
- 제목과 사고상황에 나온 기본 도로 조건
- 예: 교차로, 신호기 없음, 횡단보도, 차도, 자전거도로 자체 사고

adjustment_condition_context:
- 수정요소 표에 나온 가감 조건
- 예: 인근 자전거도로, 좌측통행, 보도통행, 야간, 시야장애
```

즉, `자전거도로`라는 단어가 있다고 무조건 기본 사고장소를 자전거도로로 보지 않는다.

`인근에 자전거도로가 있는 경우`처럼 수정요소 조건으로 나온 표현이면 `adjustment_condition_contexts.jsonl`에만 들어가는 것이 맞다.

또 `신호기 없음`은 `신호`라는 글자를 포함하지만 실제 의미는 비신호 교차로다.

그래서 `has_signal`과 `signal_context.is_signalized`는 `신호기 없음`, `신호기 없는` 표현을 먼저 확인하도록 바꾸었다.

### 15.2 shared_rule_group_chunks null 제거

공유 해설/법규 그룹 구조는 생겼지만, `shared_rule_group_chunks.jsonl`의 `text`, `metadata`가 null이면 검색 chunk로 사용할 수 없다.

기존 문제는 chunk row의 실제 텍스트 필드가 `chunk_text`인데, 공유 chunk row를 만들 때 `text` 필드를 찾고 있었기 때문이다.

그래서 `pm_auto/builder.py`의 `build_shared_chunk_row()`를 수정했다.

수정 후 기준은 다음과 같다.

```text
source_chunk_id = 원본 chunk_id
text = 원본 chunk_text
metadata = chart_no, chart_code, rule_title, chunk_type, accident_group, ratio, PM action 등 검색 메타
```

이렇게 하면 SharedRuleGroup을 독립 검색 단위로 쓰더라도 null chunk가 색인되지 않는다.

### 15.3 도표35/37/38 scenario_required 표시

도표35, 도표37, 도표38은 하나의 대표 기본과실만으로 계산하면 안 된다.

이 도표들은 `rule_scenarios.jsonl`을 우선 사용해야 한다.

```text
도표35:
- (가) 0:100
- (나) 0:100
- (다) 10:90

도표37:
- (가) 0:100
- (나) 100:0

도표38:
- (가) 20:80
- (나) 30:70
```

따라서 `pm_auto/builder.py`에 `apply_scenario_marker()`를 추가했다.

시나리오가 있는 rule은 다음처럼 표시된다.

```text
rules.jsonl:
- has_scenarios = true
- scenario_count > 0
- base_fault_type = scenario_required

base_faults.jsonl:
- base_fault_type = scenario_required
- scenario_required = true
- scenario_count > 0
- scenario_source = rule_scenarios
```

이렇게 한 이유는 graph loader나 계산 로직이 `base_faults.jsonl`만 보고 대표 비율 하나를 답으로 쓰는 실수를 막기 위해서다.

도표35/37/38은 반드시 `RuleScenario`를 먼저 보고, 사용자의 사고 설명이 어느 시나리오에 해당하는지 선택해야 한다.

### 15.4 diagram/image 산출물 제외

현재 단계의 목표는 텍스트 기반 전처리다.

따라서 PM 기준에서도 diagram/image 산출물은 제외한다.

이번에 적용한 기준은 다음과 같다.

```text
생성하지 않음:
- diagrams.jsonl
- diagram_image_path
- diagram_bbox
- page image
- crop image

삭제:
- 기존 PM 산출물에 남아 있던 99_tables_for_db/diagrams.jsonl 삭제

유지:
- [도표해설] 안의 텍스트 해설
- 사고상황 텍스트
- 기본과실 해설 텍스트
- 수정요소 적용 해설 텍스트
- 관련법규 텍스트
```

`[도표해설]`은 이름에 도표가 들어가지만 이미지가 아니라 PDF 본문 텍스트다.

그래서 JSON block type도 이미지 느낌이 강한 `diagram_explanation` 대신 `rule_explanation`으로 바꾸었다.

이렇게 하면 나중에 JSONL을 볼 때 이미지 처리 단계로 오해하지 않고, 텍스트 근거 chunk로 다룰 수 있다.

### 15.5 수정된 파일

이번 PM 추가 보정에서 수정한 파일은 다음과 같다.

```text
etl/fault_cases/src/fault_standard/preprocessing/pm_auto/classifiers.py
- road_context 생성 전 수정요소성 조건 제거
- 신호기 없음 표현을 has_signal=false로 우선 처리
- signal_context도 동일 기준으로 보정
- 중복 infer_accident_group 정의 제거

etl/fault_cases/src/fault_standard/preprocessing/pm_auto/builder.py
- rule_scenarios 존재 시 base_fault_type=scenario_required 표시
- rules.jsonl에 has_scenarios, scenario_count, base_fault_type 추가
- shared_rule_group_chunks의 text/metadata null 문제 수정
- diagrams table 생성 제거

etl/fault_cases/src/fault_standard/preprocessing/pm_auto/extractors.py
- block_type diagram_explanation을 rule_explanation으로 변경
- [도표해설]은 이미지가 아니라 텍스트 해설로 취급

etl/fault_cases/src/fault_standard/preprocessing/pm_auto/main.py
- stale diagrams.jsonl 삭제 로직 추가

etl/fault_cases/artifacts/fault_standard_output/preprocessed/2021_pm_vs_auto_nontypical_rulebook/99_tables_for_db/diagrams.jsonl
- 기존 산출물에서 삭제
```

### 15.6 다음 실행 후 확인 기준

전처리를 다시 실행한 뒤에는 아래를 확인하면 된다.

```text
road_contexts:
- 도표12/13 신호기 없음이면 has_signal=false
- 도표12~17 직진/좌회전/우회전 사고가 자전거도로로 분류되지 않음
- 도표21~23 우회전/직진 사고가 자전거도로로 분류되지 않음
- 도표37 추돌 사고에 횡단보도/보도 값이 섞이지 않음

shared_rule_group_chunks:
- text null 없음
- metadata null 없음

rules/base_faults:
- 도표35/37/38 has_scenarios=true
- 도표35/37/38 base_fault_type=scenario_required
- 도표35/37/38 계산 시 rule_scenarios 우선 사용

image/diagram:
- diagrams.jsonl 생성 안 됨
- diagram_image_path / diagram_bbox 생성 안 됨
- [도표해설] 텍스트는 rule_explanation으로 유지
```
