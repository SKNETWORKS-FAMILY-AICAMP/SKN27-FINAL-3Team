# roundabout 모듈 사용법

이 폴더는 `250624_2차로형 회전교차로사고 과실비율 비정형기준.pdf` 전처리용 모듈입니다.

## 위치

프로젝트에서는 아래 위치에 폴더째로 넣으면 됩니다.

```text
processed/traffic_ratio_stand/roundabout/
```

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python processed/traffic_ratio_stand/roundabout/main.py
```

## 입력 PDF 위치

```text
data/traffic_ratio_stand/250624_2차로형 회전교차로사고 과실비율 비정형기준.pdf
```

파일명에 `250624`, `2차로형`, `회전교차로`가 들어가면 자동으로 찾습니다.

## 출력 위치

```text
processed/traffic_ratio_stand/2025_two_lane_roundabout_rulebook/
```

## 출력 구조

```text
2025_two_lane_roundabout_rulebook/
├─ 00_manifest/
├─ 01_preface/
├─ 02_correct_roundabout_driving_method/
├─ 03_two_lane_roundabout_fault_ratio_standard/
│  ├─ 01_entry_vehicle_vs_entry_vehicle/
│  └─ 02_entry_vehicle_vs_circulating_vehicle/
└─ 99_tables_for_db/
```

## 모듈 설명

```text
config.py          경로/설정
models.py          PageText 데이터 구조
file_utils.py      JSON 저장, 파일명 정리, 해시, 중복 제거
cleaners.py        클리닝/정규화
pdf_loader.py      pdfplumber, PyMuPDF Loader
section_parser.py  머리말/통행방법 section 생성
rule_splitter.py   회전-1~회전-15 rule 분리
extractors.py      당사자/기본과실/수정요소/법규/판례/차로경로 추출
classifiers.py     사고유형/회전교차로 구조 분류
chunker.py         검색용 chunk 생성
builder.py         최종 rule JSON과 JSONL row 생성
main.py            실행 진입점
```
