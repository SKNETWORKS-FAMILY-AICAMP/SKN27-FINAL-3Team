# official_2023 모듈 사용법

이 폴더는 `230630_자동차사고 과실비율 인정기준_최종.pdf` 전처리용 모듈입니다.

## 위치

프로젝트에서는 아래 위치에 폴더째로 넣으면 됩니다.

```text
processed/traffic_ratio_stand/official_2023/
```

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python processed/traffic_ratio_stand/official_2023/main.py
```

## 입력 PDF 위치

```text
data/traffic_ratio_stand/230630_자동차사고 과실비율 인정기준_최종.pdf
```

파일명에 `230630`, `자동차사고`, `과실비율`, `인정기준`이 들어가면 자동으로 찾습니다.

## 출력 위치

```text
processed/traffic_ratio_stand/2023_official_auto_accident_rulebook/
```

## 출력 구조

```text
2023_official_auto_accident_rulebook/
├─ 00_manifest/
├─ 01_preface/
├─ 02_revision_history/
├─ 03_general_theory/
├─ 04_accident_type_fault_ratio_standards/
│  ├─ 01_vehicle_vs_pedestrian/
│  │  └─ 04_detailed_rules/
│  ├─ 02_vehicle_vs_vehicle_motorcycle/
│  │  └─ 04_detailed_rules/
│  └─ 03_vehicle_vs_bicycle_agricultural/
│     └─ 04_detailed_rules/
└─ 99_tables_for_db/
```

## 모듈 설명

```text
config.py          경로/설정
models.py          PageText 데이터 구조
file_utils.py      JSON 저장, 파일명 정리, 해시, 중복 제거
cleaners.py        클리닝/정규화
pdf_loader.py      pdfplumber, PyMuPDF Loader
section_parser.py  발간사/개정경과/총설 section 생성
rule_splitter.py   보/차/거 rule code 단위 분리
extractors.py      당사자/기본과실/수정요소/법규/판례/활용사항 추출
classifiers.py     사고유형/hierarchy 분류
chunker.py         검색용 chunk 생성
builder.py         최종 rule JSON과 JSONL row 생성
main.py            실행 진입점
```


## 거43 특수 처리

`거43`은 PDF에서 한 도표 안에 `거43-1`, `거43-2`, `거43-3`이 함께 들어있는 묶음형 rule입니다.

이 모듈은 parent code `거43`을 별도 JSON으로 저장하지 않고,
아래 3개 rule JSON으로 확장합니다.

```text
거43-1_자전거전용도로통행자전거대진로변경자동차.json
거43-2_자전거전용차로통행자전거대진로변경자동차.json
거43-3_자전거우선도로통행자전거대진로변경자동차.json
```


## 수정 히스토리

초기 버전에서는 `거43` 묶음 도표가 `거43_(가).json`처럼 잘못 저장될 수 있었습니다.
현재 버전에서는 parent code `거43`을 제거하고 `거43-1`, `거43-2`, `거43-3`으로 분리합니다.
