# 데이터 보관기간과 실제 삭제 집행

## 확정한 정책

- anonymous 1일
- guest 7일
- 인증 사용자 문서 365일
- 원본 이미지·영상 30일
- 인증 전환 시 문서의 보관기간은 전환 시점부터 365일로 다시 계산한다.
- 원본 이미지·영상은 인증 여부와 관계없이 30일 정책을 우선 적용한다.
- OCR 텍스트, 확정 사실, 리포트처럼 원본에서 파생된 문서는 인증 사용자 문서 정책을 적용한다.
- 사용자 명시 삭제는 위 보관기간보다 우선한다.

## DB·S3 실제 삭제 worker

`retention_expires_at`이 지난 업로드는 scanner worker가 다음 polling 전에
`purge_expired_uploads`로 집행한다. quarantine 객체와 clean 객체를 모두
`deleted` 또는 `not_found`로 확인한 뒤, `UploadedFile`은 민감 필드를 제거한
감사용 tombstone으로 남긴다. 파일명, 소유자, 세션·Case 연결, MIME type,
크기, URI, Agent handoff, 기존 metadata는 tombstone에 남지 않는다.

한 객체라도 삭제하지 못하면 레코드는 즉시 `deleted` 상태로 fencing하고
필요한 canonical storage reference만 내부 retry metadata에 유지한다. 다음
poll에서 retryable 정리를 다시 수행하며, 그동안 스캔 승격과 Agent handoff는
모두 차단된다. 두 객체 삭제가 확인되면 retry metadata도 제거한다.

운영 명령은 aggregate count와 안정적인 상태만 출력하며 attachment ID,
파일명, bucket, key, URI를 로그에 기록하지 않는다.

```powershell
python backend\manage.py purge_expired_uploads --dry-run --format json
python backend\manage.py purge_expired_uploads --limit 100 --fail-on-error --format text
```

scanner task role에만 두 bucket의 `canonical/uploads/*` Delete 권한을 준다.
API task role에는 clean upload 삭제 권한을 추가하지 않는다.

clean bucket은 versioning이 켜져 있으므로 `DeleteObject`의 delete marker만
확인해서는 삭제 완료로 처리하지 않는다. worker는 exact key의 모든 Versions와
DeleteMarkers를 `DeleteObjectVersion`으로 지운 다음 `ListBucketVersions`를
재실행한다. 결과가 비어 있을 때만 tombstone을 완료한다. version 목록 권한은
bucket 전체가 아니라 IAM `s3:prefix=canonical/uploads/*` 조건으로 제한한다.
