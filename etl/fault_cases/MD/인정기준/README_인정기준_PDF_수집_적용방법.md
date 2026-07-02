# 기준정보 PDF 수집 파이프라인 적용 방법

## 1. 목적

이 문서는 현재 `etl/fault_cases` 프로젝트 구조에서 KNIA 과실비율 기준정보 PDF를 수집하는 이유, 설계 방향, 실행 방법, 각 Python 파일의 역할을 정리한다.

수집 대상은 `https://accident.knia.or.kr/standard#0` 기준정보 게시판에 올라온 과실비율 관련 PDF다. 현재 사이트 기준으로 최신 기준 PDF 4개가 목록에 노출되어 있고, 각 게시글 상세 페이지에 들어가면 첨부 PDF를 다운로드할 수 있다.

## 2. 현재 폴더 구조 기준

현재 크롤링 코드는 아래 위치에 있다.

```text
etl/fault_cases/src/fault_standard/crawling/
```

설정 파일은 아래 위치에 있다.

```text
etl/fault_cases/config/crawling_settings.json
```

수집 산출물은 아래 위치에 생성된다.

```text
etl/fault_cases/artifacts/fault_standard_output/crawled/raw_source_files/
etl/fault_cases/artifacts/fault_standard_output/crawled/collection_manifest.jsonl
etl/fault_cases/artifacts/fault_standard_output/crawled/collection_quality_report.jsonl
```

## 3. 왜 이런 방식으로 수집했는가

처음에는 특정 문서 4개의 타입과 파일명을 코드 또는 JSON에 직접 적는 방식도 고려했다. 하지만 이 방식은 사이트 게시글 제목, 파일명, 등록일이 바뀔 때마다 코드나 문서 profile을 수정해야 한다.

현재 사이트 구조를 보면 기준정보 게시판 목록에 이미 필요한 단서가 있다.

- 제목에 `과실비율`, `기준`, `인정기준`, `비정형`, `PM`, `회전교차로` 같은 표현이 들어간다.
- 최신 기준 문서들이 게시판 상단에 정렬되어 있다.
- 각 게시글 상세 페이지에는 PDF 첨부가 있다.
- 첨부 파일명이 내부 숫자 파일명으로 내려올 수 있으므로 게시글 제목도 함께 보존해야 한다.

그래서 최종 설계는 "고정된 4개 문서를 박아두는 방식"이 아니라, "기준정보 게시판에서 기준 PDF 후보를 동적으로 찾는 방식"으로 잡았다.

이 방식의 근거는 다음과 같다.

- 사이트가 이미 기준정보 게시판과 첨부 구조를 제공하므로, 사람이 수동으로 URL 4개를 관리할 필요가 적다.
- 문서가 일부 개정되어 새 게시글이 올라와도 키워드 규칙과 최대 수집 개수만 유지하면 대응 가능하다.
- 다운로드 파일의 신뢰성을 manifest와 SHA256으로 추적할 수 있다.
- 수집 단계와 검증 단계를 분리해, PDF 다운로드 성공 여부와 PDF 품질 확인을 따로 관리할 수 있다.

## 4. 진행한 설계 흐름

### 4.1 초기 구조 정리

기존에 다른 프로젝트에서 가져온 크롤링 코드가 있었고, 현재 프로젝트의 폴더 구조와 맞지 않았다. 그래서 경로 계산을 현재 `etl/fault_cases` 기준으로 맞췄다.

현재 기준 패키지는 다음과 같다.

```text
etl.fault_cases.src.fault_standard
```

실행 모듈은 다음과 같다.

```text
etl.fault_cases.src.fault_standard.crawling.run_collection
```

### 4.2 하드코딩 제거 방향

특정 문서 타입을 Python 코드에 직접 적는 방식은 제거했다.

예전 방식의 문제:

```python
TARGET_DOCUMENT_TYPES = {
    "2023_official_standard",
    "2020_nontypical_standard",
}
```

이 방식은 문서 추가, 제목 변경, 게시글 변경이 생기면 코드 수정이 필요하다.

현재 방식은 `crawling_settings.json`에 "선별 규칙"만 둔다.

```json
"positive_keywords": {
  "과실비율": 35,
  "기준": 20,
  "인정기준": 35,
  "비정형": 35,
  "자동차사고": 25,
  "자동차": 15,
  "PM": 20,
  "개인형이동장치": 20,
  "회전교차로": 20
}
```

즉, 특정 파일명 4개를 외우는 코드가 아니라 게시글 제목과 상세 페이지 텍스트를 점수화해서 기준 PDF 후보를 판단한다.

### 4.3 Playwright 브라우저 자동 설치

Playwright는 Python 패키지만 설치한다고 바로 동작하지 않는다. Chromium 브라우저 바이너리를 별도로 설치해야 한다.

원래는 사용자가 아래 명령을 직접 실행해야 했다.

```powershell
python -m playwright install chromium
```

하지만 실행 편의성을 위해 `run_collection.py`가 시작될 때 Chromium 설치 여부를 확인하고, 없으면 자동 설치하도록 했다.

이 결정의 이유는 다음과 같다.

- 사용자가 `requirements.txt` 설치 후 바로 수집 명령을 실행할 가능성이 높다.
- Playwright 에러 메시지가 초보자에게는 라이브러리 설치 문제처럼 보일 수 있다.
- 수집 명령 하나로 브라우저 준비와 수집을 이어가면 재현성이 좋아진다.

## 5. 실행 방법

프로젝트 루트에서 실행한다.

```powershell
python -m etl.fault_cases.src.fault_standard.crawling.run_collection --headed --validate
```

옵션 의미:

- `--headed`: 브라우저 창을 보면서 실행한다.
- `--validate`: 다운로드 후 PDF 검증 리포트까지 만든다.

브라우저 창 없이 실행하려면 `--headed`를 빼면 된다.

```powershell
python -m etl.fault_cases.src.fault_standard.crawling.run_collection --validate
```

강제로 다시 다운로드하려면:

```powershell
python -m etl.fault_cases.src.fault_standard.crawling.run_collection --headed --validate --force
```

## 6. 설정 파일 설명

설정 파일:

```text
etl/fault_cases/config/crawling_settings.json
```

주요 항목:

```json
"source": {
  "type": "insurance_fault_standard",
  "reliability_score": 4,
  "seed_url": "https://accident.knia.or.kr/standard#0"
}
```

수집 출처와 신뢰도 정보를 정의한다. 이 값은 manifest에 기록된다.

```json
"paths": {
  "artifacts_dir": "artifacts",
  "crawled_dir": "fault_standard_output/crawled",
  "raw_source_dir": "raw_source_files",
  "logs_dir": "logs",
  "manifest_filename": "collection_manifest.jsonl",
  "quality_report_filename": "collection_quality_report.jsonl"
}
```

산출물 저장 위치를 정의한다. 코드에서 경로를 직접 박지 않고 이 설정을 읽어 경로를 만든다.

```json
"collection": {
  "id_prefix": "fault_standard",
  "unknown_document_type": "unknown",
  "max_documents": 4
}
```

수집 ID 접두사와 최대 수집 문서 수를 정의한다. 현재 기준정보 페이지에서 필요한 PDF가 4개이므로 `max_documents`는 4로 설정했다.

```json
"scoring": {
  "confirmation_threshold": 50,
  "positive_keywords": {},
  "negative_keywords": {}
}
```

게시글과 첨부파일이 기준 PDF인지 판단하는 점수 규칙이다.

## 7. Python 파일 역할

### `run_collection.py`

수집 파이프라인의 CLI 진입점이다.

역할:

- 명령행 옵션을 읽는다.
- `PipelineConfig`를 만든다.
- Chromium 브라우저 설치 여부를 확인한다.
- 수집 실행 함수 `run_collect()`를 호출한다.
- `--validate` 옵션이 있으면 검증 함수 `validate_collection()`을 호출한다.

실행 명령:

```powershell
python -m etl.fault_cases.src.fault_standard.crawling.run_collection --headed --validate
```

### `setup_browser.py`

Playwright Chromium 브라우저 준비를 담당한다.

역할:

- Chromium 실행 가능 여부를 확인한다.
- 없으면 `python -m playwright install chromium`을 자동 실행한다.

이 파일을 별도로 실행할 수도 있지만, 현재는 `run_collection.py` 안에서 자동 호출된다.

### `crawler.py`

수집 전체 흐름의 중심 파일이다.

역할:

- 기준정보 목록 페이지 접속
- 게시글 후보 수집
- 게시글 제목과 목록 텍스트 점수화
- 상세 페이지 진입
- 첨부 PDF 후보 수집
- 중복 URL, 중복 SHA256 방지
- PDF 다운로드 호출
- manifest row 생성

이 파일은 직접 다운로드를 수행하지 않고, 다운로드는 `browser_downloader.py`에 맡긴다.

### `html_parser.py`

HTML에서 게시글과 첨부파일 후보를 추출한다.

역할:

- 목록 HTML에서 `standard-content` 상세 링크를 찾는다.
- 게시글 제목, 등록일, 목록 번호, 상세 URL을 추출한다.
- 상세 HTML에서 PDF 첨부 링크를 찾는다.

BeautifulSoup 기반으로 동작한다.

### `candidate_scorer.py`

게시글이나 첨부가 기준 PDF 후보인지 점수화한다.

역할:

- 제목, 파일명, 상세 페이지 텍스트를 합친다.
- 공백과 기호를 제거해 비교하기 쉬운 문자열로 정규화한다.
- `positive_keywords`에 매칭되면 점수를 더한다.
- `negative_keywords`에 매칭되면 점수를 뺀다.
- 기준 점수 이상이면 동적 document type을 만든다.

동적 document type 예:

```text
fault_standard_2025_9aab16e6
```

이 값은 고정된 문서 profile이 아니라, 제목과 텍스트 기반으로 생성한 추적용 타입이다.

### `browser_downloader.py`

Playwright 브라우저 방식으로 PDF를 다운로드한다.

역할:

- 상세 페이지를 다시 연다.
- 첨부 링크를 클릭해 다운로드 이벤트를 기다린다.
- 다운로드 이벤트가 실패하면 Playwright request 방식으로 fallback 다운로드를 시도한다.
- 파일 크기와 SHA256을 계산한다.

숫자형 첨부 파일명일 경우 게시글 제목을 저장 파일명 fallback으로 사용한다. 이유는 사이트 내부 파일명이 `105815.pdf`처럼 사람이 이해하기 어려운 경우가 있기 때문이다.

### `direct_downloader.py`

requests 기반 직접 다운로드 보조 모듈이다.

역할:

- 첨부 URL을 직접 HTTP GET으로 다운로드한다.
- 현재 주 다운로드 방식은 브라우저 방식이지만, 직접 다운로드가 필요한 경우 사용할 수 있다.

### `manifest.py`

수집 결과를 JSONL로 기록하고 읽는 모듈이다.

역할:

- `append_jsonl()`: manifest에 row 1개 추가
- `read_jsonl()`: 기존 manifest 읽기
- `write_jsonl()`: 검증 리포트 등 JSONL 전체 쓰기

manifest를 남기는 이유:

- 어떤 PDF를 어디서 받았는지 추적하기 위해
- 저장 파일명, 원본 파일명, URL, SHA256, 수집 상태를 기록하기 위해
- 이후 전처리와 DB 적재 단계에서 입력 목록으로 쓰기 위해

### `collection_validator.py`

다운로드된 PDF 품질 검증을 담당한다.

역할:

- manifest를 읽는다.
- 저장 파일 존재 여부를 확인한다.
- PDF 확장자, 파일 크기, PDF 헤더를 확인한다.
- PyMuPDF가 있으면 PDF를 열고 페이지 수와 샘플 텍스트를 추출한다.
- SHA256 중복을 확인한다.
- 품질 리포트를 `collection_quality_report.jsonl`로 저장한다.

검증을 별도 단계로 둔 이유:

- 다운로드 성공과 PDF 품질은 다른 문제다.
- HTML 오류 페이지가 PDF 이름으로 저장될 수 있다.
- PDF가 깨졌거나 텍스트 추출이 불가능한 경우 전처리 단계에서 문제가 생긴다.

### `hash_utils.py`

파일 해시와 크기 계산을 담당한다.

역할:

- SHA256 계산
- 파일 크기 계산

SHA256을 쓰는 이유는 같은 PDF가 이름만 바뀌어도 내용 중복을 감지하기 위해서다.

### `manual_register.py`

자동 수집이 실패했을 때 수동으로 받은 PDF를 manifest에 등록하는 보조 모듈이다.

역할:

- 사용자가 직접 다운로드한 PDF 경로를 받는다.
- 제목과 파일명으로 후보 점수를 계산한다.
- manifest row를 만들어 기록한다.

자동 수집이 막히는 경우에도 이후 검증, 전처리 흐름을 유지하기 위해 둔 파일이다.

### `models.py`

수집 과정에서 사용하는 데이터 구조를 정의한다.

주요 모델:

- `StandardPostCandidate`: 게시글 후보
- `AttachmentCandidate`: 첨부파일 후보
- `DownloadResult`: 다운로드 결과
- `ManifestRow`: manifest 기록 row

### `paths.py`

파일명과 저장 경로 관련 helper를 담당한다.

역할:

- Windows에서 사용할 수 없는 문자 제거
- `.pdf` 확장자 보정
- 숫자형 PDF 파일명 판별
- 중복 파일명일 때 `_2`, `_3` 같은 suffix 부여

## 8. requirements 관련

필요한 주요 라이브러리는 다음과 같다.

```text
beautifulsoup4
playwright
requests
PyMuPDF
```

주의할 점:

- `chromium==0.0.0` 같은 pip 패키지를 requirements에 넣지 않는다.
- Chromium 브라우저는 Playwright가 별도 바이너리로 관리한다.
- 현재는 `run_collection.py` 실행 시 Chromium이 없으면 자동 설치하도록 되어 있다.

## 9. 현재 설계의 장점

- 현재 프로젝트 폴더 구조에 맞게 산출물이 분리된다.
- 기준정보 PDF 수집 로직이 `fault_standard` 도메인 안에 모여 있다.
- 특정 문서 파일명 4개를 코드에 고정하지 않는다.
- 사이트 게시글 목록을 기준으로 후보를 동적으로 판단한다.
- manifest와 quality report를 통해 수집 결과를 추적할 수 있다.
- 자동 수집 실패 시 수동 등록 경로도 유지한다.
- 다운로드와 검증이 분리되어 전처리 단계의 입력 품질을 확인할 수 있다.

## 10. 현재 기준 실행 요약

설치 후 바로 실행:

```powershell
python -m etl.fault_cases.src.fault_standard.crawling.run_collection --headed --validate
```

예상 산출물:

```text
etl/fault_cases/artifacts/fault_standard_output/crawled/raw_source_files/
etl/fault_cases/artifacts/fault_standard_output/crawled/collection_manifest.jsonl
etl/fault_cases/artifacts/fault_standard_output/crawled/collection_quality_report.jsonl
```

이 문서의 기준은 현재 프로젝트의 실제 폴더 구조와 코드 구조다. 예전 적용 문서는 참고만 하고, 실행 명령과 경로는 이 문서를 따른다.
