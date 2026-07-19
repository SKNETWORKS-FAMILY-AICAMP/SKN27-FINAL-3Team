# 과실비율 판례 최종 전처리 계획

응, 지금 전처리 과정은 거의 잡혔고, 빠진 건 **정상/실패 데이터 분리**, **날짜/필드값 정규화**, **과실비율 추출**, **최종 검증 리포트** 정도야.

내가 보기엔 최종 전처리 흐름은 이렇게 잡으면 돼.

```text
1. 정상 판례 / 실패 데이터 분리
2. 필드 분리 및 18개 필드 구조로 정리
3. 날짜, 리스트, 빈 값 정규화
4. 주문 / 이유 추출
5. 중복 판례 제거
6. 특수문자, HTML, 깨진 공백 정리
7. 계산표 / 숫자표 / 손해액 산정표 축약
8. 과실비율 후보 추출
9. 최종 검증 및 전처리 리포트 생성
10. 최종 JSONL 저장
```

기존 전처리 코드도 `all_prec_candidates_raw.jsonl`을 기준으로 정상 판례와 실패 데이터를 나누고, 텍스트를 정리한 뒤, 사건명+사건번호+법원명+선고일자가 같은 후보 중 본문 유사도가 높은 데이터를 중복 제거하는 구조였어. 기존 정리 문서도 원본 후보 데이터에서 정상/실패 분리, 표준 컬럼 정리, 중복 탐지, 품질 플래그 생성, 최종 JSONL 생성 순서로 설명하고 있어.

## 1. 정상 판례 / 실패 데이터 분리

이게 제일 먼저 들어가야 해.

원본 JSONL에는 정상 판례만 있는 게 아니라 이런 실패 데이터도 섞일 수 있잖아.

```json
{
  "Law": "일치하는 판례가 없습니다. 판례명을 확인하여 주십시오."
}
```

이런 건 과실비율 Agent에 넣으면 안 돼.
그래서 먼저 정상 판례와 실패 데이터를 분리해야 해.

정상 판례 기준은 이 정도면 됨.

```text
_case_id 또는 판례정보일련번호 있음
사건명 있음
판례내용 있음
Law 오류 메시지 없음
```

## 2. 필드 분리 및 18개 필드 구조로 정리

최종 필드는 이렇게.

```text
1. _case_id
2. 사건명
3. 사건번호
4. 선고일자
5. 법원명
6. 사건종류명
7. 판시사항
8. 판결요지
9. 참조조문
10. 참조판례
11. 판례내용
12. 주문
13. 이유
14. 과실비율
15. source_provider
16. source_reference
17. _matched_keywords
18. topic_labels
```

이 구조의 근거는 명확해.

```text
기본 판례 식별 정보
+ 법적 쟁점 정보
+ 판례 원문
+ 주문/이유 구조화
+ 과실비율 Agent 전용 필드
+ 출처/검색 보조 정보
```

## 3. 날짜, 리스트, 빈 값 정규화

이것도 필요해.

예를 들어 `선고일자`가 지금은:

```text
20251211
```

이렇게 들어오잖아.

이걸 가능하면:

```text
2025-12-11
```

로 바꾸는 게 좋아.

그리고 `_matched_keywords`, `topic_labels`는 배열로 통일하는 게 좋아.

```json
"_matched_keywords": [],
"topic_labels": []
```

값이 없으면 빈 문자열보다 `null` 또는 `[]`로 통일하는 게 나중에 처리하기 편해.

## 4. 주문 / 이유 추출

`판례내용`에서 `【주 문】`, `【이 유】`를 분리하는 단계야.

```text
판례내용 -> 원문 전체 유지
주문 -> 판결 결론
이유 -> 법원의 판단 이유
```

과실비율은 대부분 `이유` 안에서 나오니까, 이 단계가 중요해.

## 5. 중복 판례 제거

이건 기존 전처리에도 있었던 핵심 단계야.

중복 기준은 이렇게 가면 됨.

```text
사건명
사건번호
법원명
선고일자
```

이 4개가 같고, `판시사항 + 판결요지 + 판례내용` 유사도가 높으면 같은 판례 중복으로 보고 하나만 남기는 방식.

중복 제거된 데이터는 완전히 버리지 말고 별도 파일에 보관하면 좋아.

```text
duplicate_removed_cases.jsonl
```

## 6. 특수문자, HTML, 깨진 공백 정리

이건 텍스트 클리닝 단계야.

처리 대상은 이런 것들.

```text
HTML 태그
HTML 엔티티
제로폭 문자
깨진 문자
이상한 연속 공백
불필요한 줄바꿈
표가 깨지며 생긴 ? 문자
```

단, 너무 강하게 지우면 판례 문장 의미가 날아갈 수 있으니까 조심해야 해.

## 7. 계산표 / 숫자표 / 손해액 산정표 축약

이건 “삭제”보다는 **축약**이라고 표현하는 게 더 좋아.

예를 들어 이런 긴 숫자 덩어리.

```text
기간초일기간말일노임단가일수월소득상실률호프만...
```

이런 건 과실비율 판단에는 방해가 될 수 있으니까:

```text
[손해액_산정표_생략]
```

처럼 줄이는 거야.

다만 과실비율 관련 문장은 절대 지우면 안 돼.

```text
원고의 과실을 30%로 본다.
피해자의 과실을 20%로 참작한다.
피고의 책임을 70%로 제한한다.
```

이런 문장은 보존해야 해.

## 8. 과실비율 후보 추출

과실비율 Agent용 핵심 단계야.

```text
과실비율
```

전처리 최종 필드에는 `과실비율`만 둔다.

이유는 명확하다.
전처리는 원문을 정리하고 검색에 필요한 후보 값을 보강하는 단계이지, 판례의 법적 판단문과 판단 근거를 확정하는 단계가 아니다.
`과실비율_판단문`과 `과실비율_근거`를 rule 기반 전처리에서 억지로 뽑으면 오탐이 많아질 수 있다.
따라서 최종 JSONL에는 `과실비율` 후보만 넣고, 판단문/근거는 후속 검색, chunk, reranker, Agent 단계에서 evidence로 판단한다.

수집된 API 원본 데이터 기준으로 보면 과실비율은 다음처럼 여러 형태로 나온다.

```text
피해자의 과실비율은 70%, 가해자의 책임비율은 30%로 판단되었다.
피고의 책임을 70%로 제한한다.
내부적인 책임분담비율은 30:70으로 봄이 타당하다.
과실비율은 원고차량 운전자 80%, 피고차량 운전자 20%라고 판단하였다.
20% : 80%이라 볼 것이다.
치료비 × 피고 과실비율 30%
```

따라서 `과실비율`은 단순 `%`만이 아니라, **과실/책임/상계/제한 문맥 안에서 비율 표현이 나온 경우**를 후보로 본다.

비율 표현은 다음을 포함한다.

```text
70%, 30퍼센트
30:70, 20% : 80%, 5:5
7 대 3
5할, 3할
2분의 1
```

여기서 중요한 건 **비율 표현만으로 잡지 않는 것**이다.

단순히 `%`, `:`, `대`, `할`, `분의`만 보면 과실비율이 아닌 숫자도 많이 섞인다.

예를 들어 이런 표현은 과실비율이 아닐 수 있다.

```text
연 12%의 이자
통상임금의 50% 이상 가산
혈중알코올농도 0.037%
노동능력상실률 80%
장해율 10%
```

그래서 추출 기준은 다음처럼 잡는 게 좋다.

```text
비율 표현
+ 과실/책임 문맥
+ 당사자/교통사고 문맥
```

이 3개가 같이 있으면 `과실비율` 후보로 본다.

구체적인 기준은 다음과 같다.

```text
비율 표현:
%, 퍼센트, :, ：, 대, 할, 분의

과실/책임 문맥:
과실비율, 과실 비율, 책임비율, 책임 비율,
과실상계, 책임제한, 책임 제한,
과실, 책임, 손해배상책임, 참작, 제한, 인정

당사자/사고 문맥:
원고, 피고, 피해자, 가해자, 운전자, 망인,
차량, 교통사고, 사고, 공동불법행위
```

confidence를 나누면 더 안정적이다.

| 등급 | 기준 | 처리 |
|---|---|---|
| high | `과실비율`, `책임비율`, `책임분담비율`, `책임제한`, `과실상계` + 비율 | 최종 `과실비율` 요약 후보 |
| medium | `과실`, `책임`, `원고/피고/피해자/가해자` + 비율 | debug 후보로 저장하되 최종 필드 반영은 보수적으로 판단 |
| low | 비율만 있음 | 대부분 제외. 리포트용 후보만 가능 |

예시:

```json
{
  "과실비율": "30%, 70%, 30:70"
}
```

여기서 중요한 건:

```text
과실비율 = 과실/책임 문맥 안에서 발견된 대표 비율 표현 후보
```

판단문과 근거는 전처리에서 확정하지 않는다.
실제 판례는 “비율”은 한 문장에 나오고, “왜 그렇게 봤는지”는 바로 앞뒤 문단에 있는 경우가 많다.
이 영역은 단순 rule로 확정하기 어렵기 때문에 후속 RAG/Agent evidence 단계에서 판단한다.

최종적으로 8번은 이렇게 정리할 수 있다.

```text
과실비율 후보는 %가 직접 나온 표현만 보지 않는다.
70%, 30퍼센트, 30:70, 7 대 3, 5할, 2분의 1처럼 비율을 나타내는 표현을 모두 후보로 본다.

다만 이자율, 노동능력상실률, 장해율, 임금가산율, 음주수치처럼 과실비율이 아닌 숫자가 섞일 수 있으므로,
반드시 과실, 책임, 과실상계, 책임제한, 책임비율, 손해배상책임 같은 문맥어가 함께 있는 경우를 우선 추출한다.

다만 최종 전처리 필드에는 대표 `과실비율` 후보만 저장한다.
후보 문장 전체는 debug 파일에서 검토하고, 판단문/근거는 후속 검색 단계에서 다룬다.
```

한 줄 결론은 이거야.

```text
% 추출이 아니라 “과실/책임 문맥 안의 비율 표현 추출”로 정의해야 맞다.
```

## 9. 최종 검증 및 리포트 생성

품질 플래그를 최종 18개 필드에 넣을 필요는 없어.
하지만 리포트는 있는 게 좋아.

예를 들면 이런 통계.

```text
전체 row 수
정상 판례 수
실패 데이터 수
중복 제거 수
주문 추출 성공 수
이유 추출 성공 수
과실비율 추출 성공 수
계산표 축약 발생 수
최종 사용 가능 row 수
```

이 정도만 있어도 발표나 문서화할 때 근거가 생겨.

## 10. 최종 출력 파일

파일은 너무 많이 만들 필요 없어.

나는 이렇게 추천해.

```text
00_preprocess_report.json
01_invalid_cases.jsonl
02_duplicate_removed_cases.jsonl
03_cases_preprocessed.jsonl
```

실제로 Agent가 사용할 건 이거 하나야.

```text
03_cases_preprocessed.jsonl
```

## 최종 정리

네가 말한 전처리 과정에 추가하면 이렇게 돼.

```text
1. 정상 판례 / 실패 데이터 분리
2. 필드 분리 및 18개 필드 구조로 정리
3. 날짜, 리스트, 빈 값 정규화
4. 주문 / 이유 추출
5. 중복 판례 제거
6. 특수문자 및 깨진 텍스트 정리
7. 계산표 / 숫자표 / 손해액 산정표 축약
8. 과실비율 후보 추출
9. 최종 검증 리포트 생성
10. 최종 JSONL 저장
```

이렇게 쓰면 전처리 계획이 훨씬 탄탄해져.

---

# 코드 구현 계획

이 문서는 전처리 개념 정리에서 끝나는 문서가 아니라, 실제 코드를 어떤 구조로 만들고 어떤 순서로 실행할지 정리하는 구현 계획서로도 사용한다.

코드 구현의 핵심 방향은 다음이다.

```text
1. 원본 JSONL은 절대 수정하지 않는다.
2. 전처리 결과는 별도 output 폴더에 저장한다.
3. 각 단계는 함수 단위로 나누되, 실행은 하나의 pipeline script에서 한다.
4. 실패 데이터, 중복 제거 데이터, 최종 사용 데이터, 검증 리포트를 분리한다.
5. 과실비율 추출은 rule 기반으로 먼저 구현하고, 추후 성능 평가 후 고도화한다.
```

## 0. 추천 폴더 구조

현재 위치는 아래 폴더다.

```text
etl/fault_cases/src/traffic_precedents/traffic_precedents_preprocessing
```

이 폴더는 “판례 API 원본 데이터를 최종 RAG/Agent용 JSONL로 전처리하는 코드”를 두는 곳으로 사용한다.

추천 구조는 다음과 같다.

```text
traffic_precedents_preprocessing/
├── fault_ratio_preprocessing_plan.md
├── preprocess_run.py
├── before_preprocessing/
│   ├── preprocess_traffic_precedents_final_all_raw_maintext_clean.py
│   └── preprocess_traffic_precedents_method_summary_all_raw.md
├── modules/
│   ├── __init__.py
│   ├── io_utils.py
│   ├── normalizer.py
│   ├── text_cleaner.py
│   ├── section_extractor.py
│   ├── duplicate_detector.py
│   ├── table_compactor.py
│   ├── fault_ratio_extractor.py
│   └── report_builder.py
└── tests/
    ├── test_normalizer.py
    ├── test_section_extractor.py
    ├── test_fault_ratio_extractor.py
    └── test_preprocess_pipeline_sample.py
```

산출물은 코드 폴더가 아니라 artifacts 아래에 둔다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/
├── 00_preprocess_report.json
├── 01_invalid_cases.jsonl
├── 02_duplicate_removed_cases.jsonl
├── 03_cases_preprocessed.jsonl
└── debug/
    ├── fault_ratio_candidates_sample.jsonl
    ├── section_extraction_failed_sample.jsonl
    └── duplicate_groups_sample.jsonl
```

즉, 최종 구조는 `preprocess_run.py` 하나를 실행하면 위 output 폴더에 전처리 산출물이 한 번에 생성되는 방식이다.

```text
preprocess_run.py 실행
-> all_prec_candidates_raw.jsonl 읽기
-> 1~10번 전처리 pipeline 순차 실행
-> traffic_prec_pre 폴더에 report / invalid / duplicate / final JSONL 저장
```

이렇게 나누는 이유는 다음과 같다.

```text
src 폴더:
실행 코드와 전처리 로직 보관

artifacts 폴더:
전처리 실행 결과, 리포트, 디버그 샘플 보관

before_preprocessing 폴더:
기존 전처리 코드 보관용
절대 실행 대상이 아님
새 코드와 비교하거나 이전 방식의 처리 근거를 확인할 때만 참고

modules 폴더:
전처리 단계를 기능별로 분리
특히 과실비율 추출 로직만 따로 테스트하기 쉽게 구성

tests 폴더:
자동 실행 대상이 아니라 검증용 테스트 코드 보관
정규화, 주문/이유 추출, 과실비율 추출이 예상대로 동작하는지 작은 샘플로 확인
추후 rule을 수정했을 때 기존 동작이 깨졌는지 확인
```

## 1. 실행 진입점

메인 실행 파일은 하나로 둔다.

```text
preprocess_run.py
```

이 파일은 전체 pipeline을 순서대로 실행한다.

예상 실행 방식은 다음과 같다.

```bash
python etl/fault_cases/src/traffic_precedents/traffic_precedents_preprocessing/preprocess_run.py \
  --input etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_api/all_prec_candidates_raw.jsonl \
  --output-dir etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre
```

처음에는 argument를 받도록 만들고, 기본값도 코드에 둔다.

```text
input 기본값:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_api/all_prec_candidates_raw.jsonl

output-dir 기본값:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre
```

이렇게 하는 이유는 다음과 같다.

```text
1. 로컬에서 바로 실행하기 쉽다.
2. 나중에 다른 raw jsonl 파일을 넣어 재실험하기 쉽다.
3. output-dir을 바꿔서 실험 결과를 여러 번 비교할 수 있다.
```

## 2. 전체 코드 실행 순서

코드는 문서에서 정리한 1~10번 순서 그대로 실행한다.

```text
1. 정상 판례 / 실패 데이터 분리
2. 필드 분리 및 18개 필드 구조로 정리
3. 날짜, 리스트, 빈 값 정규화
4. 주문 / 이유 추출
5. 중복 판례 제거
6. 특수문자 및 깨진 텍스트 정리
7. 계산표 / 숫자표 / 손해액 산정표 축약
8. 과실비율 후보 추출
9. 최종 검증 리포트 생성
10. 최종 JSONL 저장
```

각 단계는 pipeline 내부에서 다음 함수 흐름으로 연결한다.

```text
load_jsonl
-> split_valid_invalid_cases
-> normalize_case_schema
-> normalize_values
-> extract_order_and_reason
-> remove_duplicates
-> clean_text_fields
-> compact_numeric_tables
-> extract_fault_ratio_fields
-> build_preprocess_report
-> save_outputs
```

## 3. 1단계: 정상 판례 / 실패 데이터 분리

담당 모듈:

```text
modules/io_utils.py
modules/normalizer.py
```

구현 예정 함수:

```python
def load_jsonl(path: Path) -> list[dict]:
    ...

def is_valid_case(row: dict) -> bool:
    ...

def split_valid_invalid_cases(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    ...
```

왜 하는가:

```text
원본 API 결과에는 정상 판례뿐 아니라 실패 응답도 섞일 수 있다.
실패 응답이 최종 RAG 데이터에 들어가면 검색 품질이 떨어지고,
Agent가 “일치하는 판례가 없습니다” 같은 문장을 근거로 사용할 위험이 있다.
```

진행 방식:

```text
Law 오류 메시지가 있으면 실패 데이터로 분리
_case_id 또는 판례정보일련번호가 없으면 실패 데이터로 분리
사건명 또는 판례내용이 없으면 실패 데이터로 분리
나머지는 정상 후보로 분리
```

예상 결과:

```text
정상 판례 후보 목록 생성
실패 데이터는 01_invalid_cases.jsonl에 저장
리포트에 전체 row 수, 정상 row 수, 실패 row 수 기록
```

## 4. 2단계: 필드 분리 및 18개 필드 구조로 정리

담당 모듈:

```text
modules/normalizer.py
```

구현 예정 함수:

```python
TARGET_FIELDS = [
    "_case_id",
    "사건명",
    "사건번호",
    "선고일자",
    "법원명",
    "사건종류명",
    "판시사항",
    "판결요지",
    "참조조문",
    "참조판례",
    "판례내용",
    "주문",
    "이유",
    "과실비율",
    "source_provider",
    "source_reference",
    "_matched_keywords",
    "topic_labels",
]

def normalize_case_schema(row: dict) -> dict:
    ...
```

왜 하는가:

```text
API 원본 row는 필드가 없거나 이름이 흔들릴 수 있다.
최종 Agent와 RAG 적재 코드는 일정한 schema를 기대해야 한다.
따라서 모든 row를 18개 필드 구조로 통일한다.
```

진행 방식:

```text
원본 필드를 TARGET_FIELDS에 맞게 매핑
없는 필드는 null 또는 []로 채움
source_provider는 사법정보공개포털 등으로 고정 또는 원본 출처 기반 설정
source_reference는 판례정보일련번호, URL, 사건번호 등을 조합해서 구성
```

예상 결과:

```text
모든 정상 판례가 같은 18개 필드를 가진 dict로 변환됨
이후 단계에서 KeyError 없이 안정적으로 처리 가능
```

## 5. 3단계: 날짜, 리스트, 빈 값 정규화

담당 모듈:

```text
modules/normalizer.py
```

구현 예정 함수:

```python
def normalize_date(value: str | None) -> str | None:
    ...

def normalize_list(value) -> list:
    ...

def normalize_empty(value):
    ...

def normalize_values(row: dict) -> dict:
    ...
```

왜 하는가:

```text
선고일자가 20251211처럼 들어오면 사람이 읽기 어렵고,
날짜 조건 검색이나 정렬에도 불편하다.
또 리스트 필드가 문자열, null, 배열로 섞이면 후속 처리에서 예외가 생긴다.
```

진행 방식:

```text
YYYYMMDD 형태는 YYYY-MM-DD로 변환
빈 문자열, 공백 문자열은 null로 변환
_matched_keywords, topic_labels는 항상 list로 변환
문자열 하나만 있으면 [문자열] 형태로 변환
```

예상 결과:

```text
선고일자 형식 통일
배열 필드 형식 통일
빈 값 처리 방식 통일
```

## 6. 4단계: 주문 / 이유 추출

담당 모듈:

```text
modules/section_extractor.py
```

구현 예정 함수:

```python
def extract_section(text: str, heading: str, next_headings: list[str]) -> str | None:
    ...

def extract_order_and_reason(row: dict) -> dict:
    ...
```

왜 하는가:

```text
판례내용에는 전문, 주문, 이유가 함께 들어 있다.
그중 주문은 결론이고, 이유는 판단 근거다.
과실비율 판단은 대부분 이유 안에 있으므로 이유 필드를 따로 뽑아야 검색과 추출이 좋아진다.
```

진행 방식:

```text
판례내용 원문은 그대로 보존
【주 문】 또는 [주 문] 패턴이 있으면 주문 추출
【이 유】 또는 [이 유] 패턴이 있으면 이유 추출
heading이 없으면 무리해서 추출하지 않고 null 유지
```

주의할 점:

```text
판례마다 형식이 다르므로 숫자 문단만 보고 주문/이유를 추정하지 않는다.
명확한 heading만 신뢰한다.
```

예상 결과:

```text
주문 추출 성공 row 수 증가
이유 추출 성공 row 수 증가
heading이 없는 판례는 원문 판례내용으로 fallback 가능
```

## 7. 5단계: 중복 판례 제거

담당 모듈:

```text
modules/duplicate_detector.py
```

구현 예정 함수:

```python
def build_duplicate_key(row: dict) -> tuple:
    ...

def text_similarity(a: str, b: str) -> float:
    ...

def remove_duplicates(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    ...
```

왜 하는가:

```text
같은 판례가 여러 키워드 검색 결과에서 반복 수집될 수 있다.
중복 판례가 그대로 들어가면 RAG 검색에서 특정 판례가 과대표집되고,
평가 점수나 Agent evidence가 왜곡될 수 있다.
```

진행 방식:

```text
사건명 + 사건번호 + 법원명 + 선고일자를 중복 후보 key로 사용
같은 key 안에서 판시사항 + 판결요지 + 판례내용 유사도를 비교
유사도가 높은 경우 하나만 대표로 유지
제거된 row는 02_duplicate_removed_cases.jsonl에 저장
```

예상 결과:

```text
최종 JSONL의 중복 판례 감소
중복 제거 수가 리포트에 기록됨
제거된 데이터도 별도 파일로 남아 추적 가능
```

## 8. 6단계: 특수문자 및 깨진 텍스트 정리

담당 모듈:

```text
modules/text_cleaner.py
```

구현 예정 함수:

```python
def clean_html(text: str | None) -> str | None:
    ...

def normalize_whitespace(text: str | None) -> str | None:
    ...

def clean_broken_chars(text: str | None) -> str | None:
    ...

def clean_text_fields(row: dict) -> dict:
    ...
```

왜 하는가:

```text
HTML 태그, 엔티티, 제로폭 문자, 깨진 공백이 남아 있으면
검색용 text 품질이 떨어지고, 과실비율 추출 정규식도 실패할 수 있다.
```

진행 방식:

```text
HTML 태그 제거
HTML 엔티티 디코딩
제로폭 문자 제거
연속 공백 축약
불필요한 줄바꿈 정리
단, 법률 문장의 의미를 바꿀 수 있는 문자는 무리하게 삭제하지 않음
```

예상 결과:

```text
검색과 정규식 추출에 적합한 깨끗한 텍스트 생성
원문 의미 훼손 최소화
```

## 9. 7단계: 계산표 / 숫자표 / 손해액 산정표 축약

담당 모듈:

```text
modules/table_compactor.py
```

구현 예정 함수:

```python
def is_numeric_table_like_block(text: str) -> bool:
    ...

def compact_numeric_tables(text: str | None) -> tuple[str | None, int]:
    ...

def compact_numeric_table_fields(row: dict) -> tuple[dict, int]:
    ...
```

왜 하는가:

```text
판례 본문에는 손해액 산정표, 기간별 계산표, 호프만 계수표 같은 긴 숫자표가 들어갈 수 있다.
이 숫자표는 과실비율 검색에는 방해가 되지만, 전체 삭제는 위험하다.
그래서 삭제가 아니라 축약으로 처리한다.
```

진행 방식:

```text
숫자, 금액, 날짜, 기간, 계산기호가 과도하게 반복되는 block 탐지
과실, 책임, 과실비율, 책임비율 같은 문맥어가 있는 block은 축약하지 않음
숫자표로 판단된 block만 [손해액_산정표_생략] 같은 marker로 치환
축약 횟수는 리포트에 기록
```

예상 결과:

```text
긴 숫자표로 인한 검색 noise 감소
과실비율 관련 문장은 보존
축약 발생 건수 리포트 생성
```

## 10. 8단계: 과실비율 후보 추출

담당 모듈:

```text
modules/fault_ratio_extractor.py
```

구현 예정 함수:

```python
def find_ratio_expressions(text: str) -> list[dict]:
    ...

def has_fault_context(text: str) -> bool:
    ...

def has_party_or_accident_context(text: str) -> bool:
    ...

def classify_confidence(candidate: dict) -> str:
    ...

def extract_fault_ratio_candidates(text: str) -> list[dict]:
    ...

def extract_fault_ratio_fields(row: dict) -> dict:
    ...
```

왜 하는가:

```text
과실비율 Agent가 판례를 사용할 때 가장 중요한 것은
단순히 판례 본문 전체가 아니라 과실비율 후보가 있는 판례를 먼저 식별하는 것이다.
다만 전처리는 법적 판단문과 근거를 확정하는 단계가 아니므로,
최종 필드에는 과실비율 후보만 저장한다.
판단문과 근거는 후속 RAG 검색, chunk, reranker, Agent evidence 단계에서 판단한다.
```

진행 방식:

```text
1. 이유 필드가 있으면 이유를 우선 대상으로 사용
2. 이유가 없으면 판례내용 전체를 대상으로 사용
3. 비율 표현 후보를 탐지
4. 과실/책임 문맥이 함께 있는지 확인
5. 당사자/사고 문맥이 함께 있는지 확인
6. high / medium / low confidence로 분류
7. high 후보의 비율 표현만 과실비율 필드에 요약 저장
8. high/medium/low 후보 전체는 debug/fault_ratio_candidates_sample.jsonl에서 사람이 검토
```

비율 표현 후보는 다음을 포함한다.

```text
70%, 30퍼센트
30:70, 20% : 80%, 5:5
7 대 3
5할, 3할
2분의 1
```

과실/책임 문맥은 다음을 본다.

```text
과실비율
과실 비율
책임비율
책임 비율
책임분담비율
과실상계
책임제한
책임 제한
과실
책임
손해배상책임
참작
제한
인정
```

당사자/사고 문맥은 다음을 본다.

```text
원고
피고
피해자
가해자
운전자
망인
차량
교통사고
사고
공동불법행위
```

제외 또는 low confidence로 둘 표현은 다음이다.

```text
연 12%의 이자
통상임금의 50% 이상 가산
혈중알코올농도 0.037%
노동능력상실률 80%
장해율 10%
```

예상 결과:

```text
과실비율 필드에 대표 비율 후보 요약 저장
리포트에 과실비율 추출 성공 수, high/medium/low 후보 수 기록
debug/fault_ratio_candidates_sample.jsonl에 추출 샘플 저장
```

## 11. 9단계: 최종 검증 및 리포트 생성

담당 모듈:

```text
modules/report_builder.py
```

구현 예정 함수:

```python
def build_preprocess_report(
    raw_count: int,
    valid_count: int,
    invalid_count: int,
    duplicate_removed_count: int,
    final_rows: list[dict],
    extra_stats: dict,
) -> dict:
    ...
```

왜 하는가:

```text
전처리 결과가 잘 만들어졌는지 숫자로 확인해야 한다.
특히 발표나 PM 설명에서는 “몇 건 중 몇 건을 정상 처리했고, 과실비율은 몇 건에서 추출되었는지”가 근거가 된다.
```

진행 방식:

```text
전체 row 수 집계
정상/실패 row 수 집계
중복 제거 수 집계
주문 추출 성공 수 집계
이유 추출 성공 수 집계
과실비율 추출 성공 수 집계
계산표 축약 발생 수 집계
최종 사용 가능 row 수 집계
필수 필드 누락 row 샘플 기록
```

예상 결과:

```text
00_preprocess_report.json 생성
전처리 품질을 숫자로 검증 가능
추후 전처리 로직을 바꿨을 때 이전 결과와 비교 가능
```

## 12. 10단계: 최종 JSONL 저장

담당 모듈:

```text
modules/io_utils.py
```

구현 예정 함수:

```python
def write_jsonl(path: Path, rows: list[dict]) -> None:
    ...

def write_json(path: Path, data: dict) -> None:
    ...

def save_outputs(
    output_dir: Path,
    report: dict,
    invalid_rows: list[dict],
    duplicate_rows: list[dict],
    final_rows: list[dict],
) -> None:
    ...
```

왜 하는가:

```text
Agent와 RAG 적재 단계에서 실제로 사용할 최종 파일이 필요하다.
동시에 실패 데이터와 중복 제거 데이터도 남겨야 원인을 추적할 수 있다.
```

진행 방식:

```text
00_preprocess_report.json 저장
01_invalid_cases.jsonl 저장
02_duplicate_removed_cases.jsonl 저장
03_cases_preprocessed.jsonl 저장
debug 샘플 파일 저장
```

예상 결과:

```text
최종 Agent/RAG 적재 대상:
03_cases_preprocessed.jsonl

검증 및 발표 근거:
00_preprocess_report.json

추적용 데이터:
01_invalid_cases.jsonl
02_duplicate_removed_cases.jsonl
debug/*.jsonl
```

## 13. 구현 순서

실제 코드는 한 번에 전부 완성하기보다 아래 순서로 구현한다.

```text
1. io_utils.py 작성
2. normalizer.py 작성
3. section_extractor.py 작성
4. text_cleaner.py 작성
5. table_compactor.py 작성
6. fault_ratio_extractor.py 작성
7. duplicate_detector.py 작성
8. report_builder.py 작성
9. preprocess_run.py에서 전체 pipeline 연결
10. 샘플 100건 실행
11. 전체 all_prec_candidates_raw.jsonl 실행
12. 리포트 확인 후 rule 보정
```

이 순서로 하는 이유는 다음과 같다.

```text
입출력과 schema 정규화가 먼저 잡혀야 나머지 단계가 안정적으로 돌아간다.
주문/이유 추출과 텍스트 정리는 과실비율 추출 전에 필요하다.
과실비율 추출은 가장 중요한 단계이므로 별도 모듈과 테스트를 둔다.
중복 제거는 최종 저장 전에 적용하되, 제거된 row는 별도 파일에 남긴다.
```

## 14. 1차 구현에서 하지 않을 것

1차 구현에서는 아래 작업은 하지 않는다.

```text
LLM을 사용한 과실비율 판단
판례 본문 전체의 의미 단위 자동 분해
이유 내부의 사실관계/법리판단/결론 강제 분류
임베딩 생성
Elasticsearch 적재
Agent output schema 변경
```

하지 않는 이유는 다음과 같다.

```text
이번 단계의 목적은 원본 판례를 안정적인 최종 JSONL로 전처리하는 것이다.
판례 형식이 다양하기 때문에 의미 단위 자동 분해를 무리하게 넣으면 오히려 근거가 잘릴 수 있다.
먼저 rule 기반 전처리와 과실비율 후보 추출을 안정화한 뒤,
그 결과를 보고 chunking, embedding, RAG 적재를 다시 연결하는 것이 안전하다.
```

## 15. 최종 예상 결과

이 구현이 끝나면 다음 결과가 나온다.

```text
1. 실패 API 응답이 제거된 정상 판례 JSONL
2. 18개 필드로 통일된 판례 데이터
3. 선고일자, 리스트, 빈 값이 정규화된 데이터
4. 주문/이유가 가능한 범위에서 분리된 데이터
5. 중복 판례가 제거된 데이터
6. HTML, 깨진 공백, 불필요한 특수문자가 정리된 데이터
7. 긴 계산표/숫자표가 축약된 데이터
8. 과실비율 후보가 추가된 데이터
9. 전체 처리 결과를 설명할 수 있는 검증 리포트
10. 후속 RAG/embedding/Agent 적재에 사용할 최종 JSONL
```

최종적으로 Agent가 사용할 파일은 다음이다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/03_cases_preprocessed.jsonl
```

이 파일은 이후 단계에서 다음 흐름으로 연결한다.

```text
03_cases_preprocessed.jsonl
-> 판례 chunk 생성
-> embedding 생성
-> Elasticsearch / pgvector 적재
-> BM25 / vector / hybrid 검색 평가
-> text_ml_case_search Agent evidence source로 사용
```

## 16. 생성된 JSON / JSONL 파일 설명

`preprocess_run.py`를 실행하면 전처리 결과는 아래 폴더에 생성된다.

```text
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_pre/
```

생성 파일은 크게 4종류로 나뉜다.

```text
1. 전처리 리포트
2. 실패 데이터
3. 중복 제거 데이터
4. 최종 전처리 데이터
5. debug 확인용 샘플
```

전체 구조는 다음과 같다.

```text
traffic_prec_pre/
├── 00_preprocess_report.json
├── 01_invalid_cases.jsonl
├── 02_duplicate_removed_cases.jsonl
├── 03_cases_preprocessed.jsonl
└── debug/
    ├── fault_ratio_candidates_sample.jsonl
    └── duplicate_groups_sample.jsonl
```

### 16.1. `00_preprocess_report.json`

전처리 전체 실행 결과를 요약한 리포트 파일이다.

이 파일은 Agent나 RAG가 직접 사용하는 데이터가 아니라, 전처리가 제대로 되었는지 확인하기 위한 검증 파일이다.

주요 내용은 다음과 같다.

```text
전체 raw row 수
정상 판례 row 수
실패 데이터 row 수
중복 제거 row 수
최종 row 수
주문 추출 성공 수
이유 추출 성공 수
과실비율 추출 성공 수
필드별 누락 개수
과실비율 후보 confidence 통계
숫자표/계산표 축약 개수
```

예상 형태는 다음과 같다.

```json
{
  "generated_at": "2026-07-11T...",
  "row_counts": {
    "raw": 17588,
    "valid_before_dedup": 15771,
    "invalid": 1817,
    "duplicate_removed": 1234,
    "final": 14537
  },
  "extraction_counts": {
    "order_extracted": 12000,
    "reason_extracted": 11800,
    "fault_ratio_extracted": 900
  }
}
```

여기서 중요한 것은 숫자 자체보다 다음을 확인하는 것이다.

```text
raw 수와 valid + invalid 수가 맞는가
final 수가 valid 수보다 작거나 같은가
주문/이유 추출 수가 0이 아닌가
과실비율 추출 수가 비정상적으로 0이 아닌가
missing_field_counts에서 필수 필드 누락이 과도하지 않은가
```

이 파일은 발표나 문서화에서도 근거로 쓸 수 있다.

예를 들어 다음처럼 말할 수 있다.

```text
전체 API 후보 중 정상 판례와 실패 응답을 분리했고,
중복 판례를 제거한 뒤 최종 사용 가능한 JSONL을 생성했습니다.
또 주문/이유/과실비율 추출 성공 건수를 리포트로 남겨 전처리 품질을 확인할 수 있게 했습니다.
```

### 16.2. `01_invalid_cases.jsonl`

정상 판례로 사용할 수 없는 row를 따로 저장한 파일이다.

이 파일도 Agent나 RAG가 직접 사용하지 않는다.

분리 대상은 다음과 같다.

```text
JSON 파싱 실패 row
Law 오류 메시지 row
_case_id 또는 판례정보일련번호가 없는 row
사건명이 없는 row
판례내용이 없는 row
```

예상 형태는 다음과 같다.

```json
{
  "Law": "일치하는 판례가 없습니다. 판례명을 확인하여 주십시오.",
  "_invalid_reason": "api_no_matching_precedent"
}
```

또는 다음처럼 들어갈 수 있다.

```json
{
  "_input_line_no": 123,
  "_json_decode_error": "...",
  "_raw_line_preview": "...",
  "_invalid_reason": "json_decode_error"
}
```

이 파일을 남기는 이유는 다음과 같다.

```text
실패 데이터를 조용히 버리지 않기 위해서
어떤 이유로 제외되었는지 확인하기 위해서
API 수집 품질을 나중에 다시 점검하기 위해서
전처리 리포트의 invalid 수와 실제 invalid row를 맞춰보기 위해서
```

확인 기준은 다음이다.

```text
이 파일에 있는 row는 최종 03_cases_preprocessed.jsonl에 들어가면 안 된다.
_invalid_reason이 있어야 한다.
실패 이유가 대부분 설명 가능한 범위여야 한다.
```

### 16.3. `02_duplicate_removed_cases.jsonl`

중복 판례로 판단되어 최종 데이터에서 제거된 row를 저장한 파일이다.

이 파일도 Agent나 RAG가 직접 사용하지 않는다.

중복 판단 기준은 다음이다.

```text
사건명
사건번호
법원명
선고일자
```

이 4개가 같은 후보끼리 묶은 뒤, 다음 텍스트를 비교한다.

```text
판시사항 + 판결요지 + 판례내용
```

유사도가 기준값 이상이면 같은 판례의 중복 수집본으로 보고 하나만 대표로 남긴다.

제거된 row에는 다음과 같은 추적 필드가 붙는다.

```text
_duplicate_reason
_duplicate_similarity
_duplicate_representative_case_id
```

예상 형태는 다음과 같다.

```json
{
  "_case_id": "123456",
  "사건명": "구상금",
  "사건번호": "2024다00000",
  "법원명": "대법원",
  "선고일자": "2025-01-01",
  "_duplicate_reason": "same_key_high_text_similarity",
  "_duplicate_similarity": 0.97,
  "_duplicate_representative_case_id": "123456"
}
```

이 파일을 남기는 이유는 다음과 같다.

```text
중복 제거가 과하게 되었는지 확인하기 위해서
어떤 row가 대표로 남고 어떤 row가 제거되었는지 추적하기 위해서
RAG 검색에서 같은 판례가 반복 노출되는 것을 줄이기 위해서
필요하면 중복 제거 기준을 다시 조정하기 위해서
```

확인 기준은 다음이다.

```text
이 파일에 있는 row는 최종 03_cases_preprocessed.jsonl에 중복으로 들어가면 안 된다.
_duplicate_similarity가 기준값 이상이어야 한다.
대표 case_id가 기록되어 있어야 한다.
중복 제거 수가 비정상적으로 너무 많으면 기준을 재검토해야 한다.
```

### 16.4. `03_cases_preprocessed.jsonl`

최종 전처리 결과 파일이다.

실제로 후속 RAG, embedding, Agent 적재에서 사용할 파일은 이 파일이다.

이 파일에는 최종 18개 필드만 들어간다.

```text
1. _case_id
2. 사건명
3. 사건번호
4. 선고일자
5. 법원명
6. 사건종류명
7. 판시사항
8. 판결요지
9. 참조조문
10. 참조판례
11. 판례내용
12. 주문
13. 이유
14. 과실비율
15. source_provider
16. source_reference
17. _matched_keywords
18. topic_labels
```

이 파일에는 debug용 내부 필드가 들어가면 안 된다.

들어가면 안 되는 필드 예시는 다음과 같다.

```text
_fault_ratio_candidates
_numeric_table_compaction_count
_duplicate_similarity
_duplicate_reason
_json_decode_error
_invalid_reason
```

예상 형태는 다음과 같다.

```json
{
  "_case_id": "606179",
  "사건명": "구상금",
  "사건번호": "...",
  "선고일자": "2025-...",
  "법원명": "대법원",
  "사건종류명": "민사",
  "판시사항": "...",
  "판결요지": "...",
  "참조조문": "...",
  "참조판례": "...",
  "판례내용": "...",
  "주문": "...",
  "이유": "...",
  "과실비율": "70%, 30%",
  "source_provider": "...",
  "source_reference": "...",
  "_matched_keywords": [
    "교통사고"
  ],
  "topic_labels": []
}
```

이 파일의 확인 기준은 다음이다.

```text
모든 row가 18개 필드를 가져야 한다.
선고일자는 가능하면 YYYY-MM-DD 형태여야 한다.
_matched_keywords, topic_labels는 list여야 한다.
판례내용은 원문 전체를 유지해야 한다.
주문/이유는 heading이 있는 경우만 채워지고, 없으면 null일 수 있다.
과실비율은 없는 판례도 있으므로 null일 수 있다.
과실비율이 있더라도 판단문/근거는 최종 전처리 필드에 넣지 않는다.
```

이 파일은 이후 다음 단계로 넘어간다.

```text
03_cases_preprocessed.jsonl
-> 판례 chunk 생성
-> embedding 생성
-> Elasticsearch / pgvector 적재
-> 검색 평가
-> Agent evidence source로 사용
```

### 16.5. `debug/fault_ratio_candidates_sample.jsonl`

과실비율 추출 결과를 사람이 확인하기 위한 debug 샘플 파일이다.

이 파일은 최종 Agent/RAG 적재 대상이 아니다.

들어가는 내용은 다음과 같다.

```text
_case_id
사건명
과실비율
candidate_count
candidates
```

`candidates`에는 과실비율 후보로 잡힌 표현과 confidence가 들어간다.

예상 형태는 다음과 같다.

```json
{
  "_case_id": "606179",
  "사건명": "구상금",
  "과실비율": "70%, 30%",
  "candidate_count": 2,
  "candidates": [
    {
      "text": "70%",
      "sentence": "이 사고에서 피해자의 과실비율은 70%, 가해자의 책임비율은 30%로 판단되었다.",
      "confidence": "high",
      "has_fault_context": true,
      "has_party_or_accident_context": true
    }
  ]
}
```

이 파일을 보는 이유는 다음이다.

```text
과실비율 후보가 너무 넓게 잡히는지 확인
연 12% 이자, 노동능력상실률 80%, 장해율 10% 같은 오탐이 high로 잡히지 않는지 확인
30:70, 7 대 3, 5할 같은 표현이 누락되지 않는지 확인
confidence 분류가 적절한지 확인
```

확인 기준은 다음이다.

```text
과실비율/책임비율/책임분담비율 문맥의 비율은 high로 잡히는 것이 좋다.
일반 과실/책임 문맥과 당사자/사고 문맥이 함께 있으면 medium으로 잡힐 수 있다.
이자율, 장해율, 임금가산율, 음주수치 등은 low이거나 최종 판단문에서 빠져야 한다.
최종 JSONL에는 과실비율_판단문/과실비율_근거 필드를 만들지 않는다.
```

### 16.6. `debug/duplicate_groups_sample.jsonl`

중복 제거 그룹을 사람이 확인하기 위한 debug 샘플 파일이다.

이 파일도 최종 Agent/RAG 적재 대상이 아니다.

들어가는 내용은 다음과 같다.

```text
duplicate_key
representative_case_id
group_size
removed_count
similarity_threshold
```

예상 형태는 다음과 같다.

```json
{
  "duplicate_key": [
    "구상금",
    "2024다00000",
    "대법원",
    "2025-01-01"
  ],
  "representative_case_id": "123456",
  "group_size": 3,
  "removed_count": 2,
  "similarity_threshold": 0.9
}
```

이 파일을 보는 이유는 다음이다.

```text
같은 사건명/사건번호/법원명/선고일자로 잘 묶였는지 확인
중복 제거가 과하게 발생하지 않았는지 확인
대표 row가 존재하는지 확인
similarity_threshold 조정이 필요한지 판단
```

확인 기준은 다음이다.

```text
group_size는 2 이상이어야 한다.
removed_count는 group_size보다 작아야 한다.
representative_case_id가 있어야 한다.
서로 다른 판례가 같은 그룹으로 잘못 묶이면 중복 기준을 재검토해야 한다.
```

## 17. 최종 사용 파일과 확인 파일 구분

최종 사용 파일은 하나다.

```text
03_cases_preprocessed.jsonl
```

아래 파일들은 검증과 추적을 위한 파일이다.

```text
00_preprocess_report.json
01_invalid_cases.jsonl
02_duplicate_removed_cases.jsonl
debug/fault_ratio_candidates_sample.jsonl
debug/duplicate_groups_sample.jsonl
```

정리하면 다음과 같다.

| 파일 | 실제 RAG/Agent 사용 | 목적 |
|---|---|---|
| `00_preprocess_report.json` | 아니오 | 전처리 통계 확인 |
| `01_invalid_cases.jsonl` | 아니오 | 실패/제외 데이터 추적 |
| `02_duplicate_removed_cases.jsonl` | 아니오 | 중복 제거 데이터 추적 |
| `03_cases_preprocessed.jsonl` | 예 | 최종 전처리 결과 |
| `debug/fault_ratio_candidates_sample.jsonl` | 아니오 | 과실비율 추출 샘플 확인 |
| `debug/duplicate_groups_sample.jsonl` | 아니오 | 중복 그룹 샘플 확인 |
