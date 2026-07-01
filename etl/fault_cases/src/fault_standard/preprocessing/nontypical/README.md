# nontypical 모듈 사용법

이 폴더는 `210107_2020년 비정형사고 과실비율 기준.pdf` 전처리용 모듈입니다.

## 위치

프로젝트에서는 아래 위치에 폴더째로 넣으면 됩니다.

```text
processed/traffic_ratio_stand/nontypical/
```

## 실행

프로젝트 루트에서 실행합니다.

```powershell
python processed/traffic_ratio_stand/nontypical/main.py
```

## 입력 PDF 위치

```text
data/traffic_ratio_stand/210107_2020년 비정형사고 과실비율 기준.pdf
```

## 출력 위치

```text
processed/traffic_ratio_stand/2020_nontypical_accident_rulebook/
```

## 출력 구조

```text
2020_nontypical_accident_rulebook/
├─ 00_manifest/
├─ 01_summary_table/
├─ 02_detailed_fault_ratio_standards/
└─ 99_tables_for_db/
```

## 모듈 설명

```text
config.py          경로/설정
models.py          PageText 데이터 구조
file_utils.py      JSON 저장, 파일명 정리, 해시, 중복 제거
cleaners.py        클리닝/정규화
pdf_loader.py      pdfplumber, PyMuPDF Loader
summary_parser.py  요약표 파싱
rule_splitter.py   상세 rule 분리
extractors.py      당사자/기본과실/수정요소/법규/사례 추출
classifiers.py     사고유형/도로환경/우선권 분류
chunker.py         검색용 chunk 생성
builder.py         최종 rule JSON과 JSONL row 생성
main.py            실행 진입점
```
