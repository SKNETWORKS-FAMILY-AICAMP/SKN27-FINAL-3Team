# 기술 검증 리포트

이 폴더는 분야별 구현이 완료되거나 평가 실행이 끝날 때 작성하는 검증 기록의 기준 위치다.

## 작성 원칙

- 분야·이슈·날짜별로 별도 Markdown 파일을 만든다.
- 구현 여부, 실제 연결 여부, 실행 명령, 테스트 결과, 외부 서비스 실행 여부를 분리해 기록한다.
- 실행하지 않은 Provider·RAGAS·운영 DB 결과를 통과한 것처럼 기록하지 않는다.
- 사용자 입력, OCR 원문, API 키, 파일 경로, 검색 원문 전문은 리포트에 넣지 않는다.
- 모델·chunk·검색 backend를 비교한 경우 corpus snapshot, metadata, 비용, 지연시간, 한계와 전환 결론을 함께 기록한다.

## 파일명

`YYYY-MM-DD-<domain>-<topic>-report.md`

예: `2026-07-21-legal-rag-pgvector-evaluation-report.md`

## 현재 리포트

- [법령 RAG PostgreSQL lexical·pgvector 평가](legal-rag/2026-07-21-legal-rag-pgvector-evaluation-report.md)
