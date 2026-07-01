# Object storage adapter 연결 기록 - 2026-06-30

## 결론

Object storage는 실제 binary 업로드 구현 전에 canonical metadata 전환 지점부터 만든다.
현재 단계는 `object_storage_adapter.v1` envelope를 `uploaded_files`, `reports` metadata에
저장하고, 기존 mock sidecar URI는 `source_storage_uri`로 보존한다.

## 적용 범위

- 파일 업로드
  - `uploaded_files.storage_uri`는 adapter가 만든 `s3://...` URI를 사용한다.
  - mock local sidecar URI는 `uploaded_files.metadata.source_storage_uri`에 남긴다.
  - agent handoff의 `storage_uri`도 object-storage URI를 기준으로 맞춘다.
- 리포트 저장/다운로드
  - `reports.storage_uri`는 adapter URI를 사용한다.
  - `reports.metadata.object_storage`와 `reports.content.object_storage`에 bucket/key를 저장한다.
  - download 응답 header에 `X-Report-Object-Key`, `X-Report-Object-Policy`를 추가한다.

## 정책

- policy version: `object_storage_adapter.v1`
- provider 기본값: `mock_s3`
- bucket 기본값: `skn27-demo-object-storage`
- prefix 기본값: `canonical`
- signed URL TTL 기본값: 900초
- 현재 단계는 `metadata_only_adapter`라서 실제 binary write는 하지 않는다.
- 실제 object body가 필요하면 Django download response가 fallback 역할을 한다.

## 남은 일

1. 실제 S3/MinIO client를 붙여 binary write/read를 수행한다.
2. signed URL 발급 경로를 Django download fallback과 분리한다.
3. 업로드 바이러스 검사, OCR 원문 저장 금지 정책, report retention 정책을 object key lifecycle과 연결한다.
