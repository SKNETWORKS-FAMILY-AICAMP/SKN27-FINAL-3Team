# 법령 데이터 최신성 검증 Runbook

## 목적

법령 수집·재구축 결과가 운영 배포에 사용할 수 있는 상태인지 source별로 확인하고,
검증 결과를 release 증적으로 보관한다. 실제 운영 API 비밀값, 운영 DB, 재임베딩
비용 승인이 없는 환경에서는 이 문서의 성공 결과를 운영 적재 성공으로 주장하지
않는다.

## 증적 계약

법령 파이프라인은 실행마다 다음 파일을 생성한다.

- `reports/run_summary.json`
- 계약 버전: `legal_ingestion_run_summary.v2`
- 실행 식별자: `run_id`
- 전체 데이터 버전: `dataset_version`
- source별 상태: `source_summaries`
- source별 수집 시각: `collected_at`
- source별 마지막 검증 시각: `last_verified_at`
- source별 적용 시작·종료일: `first_effective_at`, `last_effective_at`
- source별 데이터 버전: `data_version`
- source별 버전·문서·chunk·검색 가능 chunk 건수
- source별 안전한 오류 코드: `errors`

run summary에는 원문, 비밀값, 임베딩 벡터를 저장하지 않는다.

## 배포 전 실행 순서

### 1. 운영 승인값 확인

운영 책임자가 다음 값을 승인한다.

- 최대 허용 경과시간(`max_age_hours`)
- 이번 release의 필수 법령 source
- 운영 데이터 사용과 재임베딩 비용
- 증적 보관 위치와 접근 권한

최대 허용 경과시간은 코드에 고정하지 않는다. release 승인 기록에 실제 사용값을
남긴다.

### 2. 기존 검증 seed를 기준으로 최신 source를 dry-run 대조

기존 검증 manifest는 저장소 밖의 읽기 전용 경로에 둔다. 법제처 자격증명은
환경에만 주입하고 명령·로그·증적에 값을 기록하지 않는다.

수집기 자체의 source 연결과 run summary 생성만 독립적으로 진단해야 하면 별도의
빈 출력 경로에서 다음 명령을 사용할 수 있다. 이 단독 실행 결과만으로 승인 seed가
완성됐거나 운영 배포가 승인됐다고 판단하지 않는다.

```powershell
python -m etl.legal.ingestion.run `
  --manifest etl/legal/manifests/traffic_law_manifest.yaml `
  --mode artifact `
  --output-dir output/law_ingestion
```

```powershell
$ExistingManifest = "C:\secure\existing-rag-seed\rag-seed-manifest.json"
$PreviewRoot = "C:\secure\legal-seed-preview-$(Get-Date -Format yyyyMMdd-HHmmss)"

$PreviewJson = (& python backend/manage.py build_approved_legal_rag_seed `
  --source-config etl/legal/manifests/traffic_law_manifest.yaml `
  --existing-manifest $ExistingManifest `
  --output-root $PreviewRoot `
  --max-age-hours 168 `
  --client law_go_kr `
  --dry-run `
  --format json) | Out-String
if ($LASTEXITCODE -ne 0) { throw "Approved legal seed dry-run failed." }
$Preview = $PreviewJson | ConvertFrom-Json
$Preview | ConvertTo-Json -Depth 6
```

`--dry-run`은 법제처 source를 실제 수집하고 기존 embedding을
`chunk_id + embedding_text_hash`로 대조하지만 OpenAI, S3, 운영 DB는 호출하지
않는다. 출력의 `dataset_version`, `plan_sha256`, `reused`, `changed`, `new`,
`removed`, `pending`을 승인 기록에 남긴다.
기존 embedding baseline만으로 freshness를 갱신하지 않는다. 다음 명령만 실행해 현재 시각을 새 검증 시각으로
주장하는 것은 금지한다.

```powershell
python -m etl.legal.rebuild_artifacts_from_embeddings `
  --manifest etl/legal/manifests/traffic_law_manifest.yaml `
  --embeddings output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl `
  --output-dir output/law_ingestion
```

### 3. 변경분 비용 승인 후 exact plan만 실행

`pending`이 0이면 유료 호출 없이 final build를 실행할 수 있다. 1개 이상이면
model `text-embedding-3-large`, dimensions `1024`, pending 건수와 예상 batch 수를
운영 책임자가 승인한다. dry-run 이후 source나 pending identity가 바뀌면
`plan_sha256`이 달라지고 기존 승인은 무효다.

```powershell
$FinalRoot = "C:\secure\legal-seed-final-$(Get-Date -Format yyyyMMdd-HHmmss)"

python backend/manage.py build_approved_legal_rag_seed `
  --source-config etl/legal/manifests/traffic_law_manifest.yaml `
  --existing-manifest $ExistingManifest `
  --output-root $FinalRoot `
  --dataset-version $Preview.dataset_version `
  --approved-plan-sha256 $Preview.plan_sha256 `
  --max-age-hours 168 `
  --client law_go_kr `
  --allow-paid-embedding `
  --format json
if ($LASTEXITCODE -ne 0) { throw "Approved legal seed final build failed." }

python backend/manage.py verify_production_rag_seed_manifest `
  --manifest "$FinalRoot\rag-seed-manifest.json" `
  --format json
if ($LASTEXITCODE -ne 0) { throw "Final seed verification failed." }
```

`pending`이 0이면 `--approved-plan-sha256`와 `--allow-paid-embedding`을 생략한다.
OpenAI 호출 승인은 법령 변경분에만 적용된다. 이후 Pilot seed maintenance가
수행할 수 있는 review-case 최대 904개 embedding은 별도 비용 승인 항목이다.

### 4. immutable S3 prefix에 승인 bundle 업로드

manifest SHA를 새 versioned prefix로 사용한다. final bundle의 `data/` 네 artifact와
manifest만 올리며 local planning work file은 올리지 않는다.

```powershell
$NewManifestSha = (Get-FileHash "$FinalRoot\rag-seed-manifest.json" -Algorithm SHA256).Hash.ToLowerInvariant()
$SeedPrefix = "s3://skn27-pilot-908708651753-clean/_rag-seed/$NewManifestSha/"

aws s3 cp "$FinalRoot\rag-seed-manifest.json" "${SeedPrefix}rag-seed-manifest.json" `
  --region ap-northeast-2 --only-show-errors --no-cli-pager
aws s3 cp "$FinalRoot\data" "${SeedPrefix}data/" --recursive `
  --region ap-northeast-2 --only-show-errors --no-cli-pager
if ($LASTEXITCODE -ne 0) { throw "Immutable seed upload failed." }
```

### 5. candidate stage, seed maintenance, promotion 순서

새 `LEGAL_DATASET_VERSION`, 보수적인 `LEGAL_DATASET_VERIFIED_AT`,
`LEGAL_RAG_SEED_MANIFEST_SHA256`를 넣은 안전한 runtime env를 준비한다. 현재 release를
직접 수정하지 않는다.

1. `Deploy-Pilot.ps1 -StageForReleaseUpdate`로 candidate private services를 stage한다.
2. 별도 review-case 비용 승인 후 `Load-Rag-Seed-Pilot.ps1`을 새 S3 prefix와 manifest
   SHA로 실행한다.
3. `.production-rag-seed.complete`, release-local evidence, 법령 graph, pgvector와 검색
   smoke가 모두 성공했는지 확인한다.
4. 동일 release tag와 `-SkipBuild`로 `Deploy-Pilot.ps1` promotion을 실행한다.
5. transaction gate 성공 뒤 `Confirm-PilotOperationalAcceptance.ps1`로 600초 연속
   acceptance를 확인한다.
6. 이 성공 증거가 확보된 후에만 후속 CodePipeline **App Release** 수동 승인을
   재개한다. 이전에 descriptor 부재로 실패한 실행을 그대로 재시도하지 않는다.

### 6. 최신성 자동 판정

운영 책임자가 승인한 정수 시간값을 입력한다.

```powershell
$MaxAgeHours = Read-Host "승인된 최대 허용 경과시간을 시간 단위 정수로 입력"
python etl/legal/validate_run_summary.py `
  --summary output/law_ingestion/reports/run_summary.json `
  --max-age-hours $MaxAgeHours `
  --output output/law_ingestion/reports/freshness_validation.json
```

특정 source를 필수로 고정해야 하면 `--required-source`를 반복한다.

```powershell
python etl/legal/validate_run_summary.py `
  --summary output/law_ingestion/reports/run_summary.json `
  --max-age-hours $MaxAgeHours `
  --required-source road_traffic_act `
  --required-source road_traffic_act_enforcement_decree `
  --output output/law_ingestion/reports/freshness_validation.json
```

검증기는 다음 중 하나라도 있으면 종료 코드 `1`과 `status: failed`를 반환한다.

- `missing_sources`: run summary에 없는 필수 source
- `failed_sources`: 적재 실패 또는 마지막 검증 시각이 없는 source
- `stale_sources`: 승인된 `max_age_hours`보다 오래된 source

이 경우 배포를 중단하고 공급자 복구 또는 승인 seed 재실행 후 새 `run_id`로
처음부터 다시 검증한다. 기존 실패 증적을 성공 파일로 덮어쓰지 않는다.

## 운영 DB 검증

freshness validation이 성공한 뒤에도 다음 운영 DB 검증을 별도로 수행한다.

1. source별 row 수
2. pgvector index 존재와 유효성
3. 법령·심의사례 공통 embedding 공간
4. 대표 검색 smoke
5. 대표 검색 latency
6. release marker 생성 여부
7. 실패 적재 rollback 결과

운영 DB 접근 권한이나 비밀값이 없으면 이 단계는 성공으로 표시하지 않는다.

## Release 증적 보관

다음 파일과 값을 같은 release 증적 디렉터리에 보관한다.

- `reports/run_summary.json`
- `reports/freshness_validation.json`
- `run_id`
- `dataset_version`
- source별 `data_version`
- 실제 사용한 `max_age_hours`
- 운영 DB readiness·대표 검색 결과
- 배포 commit과 image digest

증적 디렉터리는 release별로 분리하고 배포 후 일반 애플리케이션 계정이 수정할 수
없도록 운영 권한을 제한한다.

## 실패 후 재실행

1. `missing_sources`면 manifest와 source enable 상태를 확인한다.
2. `failed_sources`면 `errors`와 ingestion log에서 실패 단계를 확인한다.
3. `stale_sources`면 운영 승인 하에 해당 source를 다시 수집·재색인한다.
4. 새 실행은 새 `run_id`와 `dataset_version`을 생성해야 한다.
5. validation을 다시 실행한다.
6. 성공한 새 증적과 이전 실패 증적을 함께 보관한다.
7. 운영 DB 검증까지 성공한 뒤에만 배포 승인을 재개한다.
