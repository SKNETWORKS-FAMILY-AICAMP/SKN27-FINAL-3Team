# Task 3 실행 보고서

## 수행 내용

- 읽기 전용 원본 `C:\dev\project\SKN27-RAG-rescue\etl\fault_cases\legacy_runnable`에서 Markdown 28개를 조사했다.
- 제외 대상 `fault_standard_neo4j_v8_v9\NEW_ABC_TEST_V6\models\Qwen3-Embedding-4B\README.md` 1개를 제외하고 27개를 `etl/fault_cases/Fault_cases_MD/legacy_runnable`에 상대 경로 그대로 복사했다.
- 복사본은 원본 바이트를 변경하지 않는 파일 복사로 만들었다.
- 루트 `README.md`는 이 트리가 문서 전용 역사 기록이며, 전체 실행 가능 아카이브는 local rescue에 있고 현재 런타임이 이에 의존하면 안 된다는 점을 한국어로 명시했다.

## 검증 방법

다음 PowerShell 검증은 제외 규칙을 적용한 원본과 대상의 상대 경로 집합, 파일 수, SHA-256 해시를 비교한다.

```powershell
$src = 'C:\dev\project\SKN27-RAG-rescue\etl\fault_cases\legacy_runnable'
$dst = 'etl\fault_cases\Fault_cases_MD\legacy_runnable'
$excluded = Join-Path $src 'fault_standard_neo4j_v8_v9\NEW_ABC_TEST_V6\models\Qwen3-Embedding-4B\README.md'
$source = Get-ChildItem -LiteralPath $src -Recurse -File -Filter *.md |
  Where-Object { $_.FullName -ne $excluded } |
  ForEach-Object { [pscustomobject]@{ Path=$_.FullName.Substring($src.Length+1); Hash=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash } } |
  Sort-Object Path
$destination = Get-ChildItem -LiteralPath $dst -Recurse -File -Filter *.md |
  Where-Object { $_.Name -ne 'README.md' -or $_.DirectoryName -ne (Resolve-Path -LiteralPath $dst).Path } |
  ForEach-Object { [pscustomobject]@{ Path=$_.FullName.Substring((Resolve-Path -LiteralPath $dst).Path.Length+1); Hash=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash } } |
  Sort-Object Path
($source.Count -eq 27) -and ($destination.Count -eq 27) -and (@(Compare-Object $source $destination -Property Path,Hash).Count -eq 0)
```

결과는 `True`여야 하며, 스테이징 후 `git diff --cached --name-only`는 이 작업의 `.md` 경로만 포함하는지 확인한다. 또한 모델, ZIP, Parquet, 생성 산출물, 레거시 런타임 소스는 스테이징하지 않는다.

## 검증 결과

- 원본 선택 Markdown: 27개
- 대상 복사 Markdown(루트 인덱스 제외): 27개
- 상대 경로 및 SHA-256 불일치: 0개
- 해시 검증 결과: `True`
- 스테이징된 비-Markdown 경로: 0개
- 모델 README 제외 대상은 대상 트리에 존재하지 않는다.
