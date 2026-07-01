# pm_auto 모듈 사용법

이 폴더는 `!!210624_PM대자동차사고과실비율비정형기준_송부(2021).pdf` 전처리용 모듈입니다.

## 위치

프로젝트에서는 아래 위치에 폴더째로 넣으면 됩니다.

```text
processed/traffic_ratio_stand/pm_auto/
```

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python processed/traffic_ratio_stand/pm_auto/main.py
```

## 입력 PDF 위치

```text
data/traffic_ratio_stand/!!210624_PM대자동차사고과실비율비정형기준_송부(2021).pdf
```

파일명에 `PM`, `자동차`, `과실비율`이 들어가면 자동으로 찾습니다.

## 출력 위치

```text
processed/traffic_ratio_stand/2021_pm_vs_auto_nontypical_rulebook/
```

## 출력 구조

```text
2021_pm_vs_auto_nontypical_rulebook/
├─ 00_manifest/
├─ 01_overview/
├─ 02_scope/
├─ 03_terms/
├─ 04_adjustment_factor_explanation/
├─ 05_detailed_fault_ratio_standards/
│  ├─ 01_signal_violation/
│  ├─ 02_unsignalized_intersection/
│  ├─ 03_one_way_violation/
│  ├─ 04_straight_left_right_turn/
│  ├─ 05_crossing_and_sidewalk/
│  ├─ 06_centerline_and_road_entry/
│  ├─ 07_lane_change_and_rear_end/
│  └─ 08_bicycle_road_sidewalk_door_opening/
└─ 99_tables_for_db/
```

## 모듈 설명

```text
config.py          경로/설정
models.py          PageText 데이터 구조
file_utils.py      JSON 저장, 파일명 정리, 해시, 중복 제거
cleaners.py        클리닝/정규화
pdf_loader.py      pdfplumber, PyMuPDF Loader
section_parser.py  개요/적용범위/용어/수정요소 section 생성
rule_splitter.py   도표1~도표38 rule 분리
extractors.py      당사자/기본과실/수정요소/법규/판례/PM context 추출
classifiers.py     사고유형/도로환경/신호 context 분류
chunker.py         검색용 chunk 생성
builder.py         최종 rule JSON과 JSONL row 생성
main.py            실행 진입점
```
