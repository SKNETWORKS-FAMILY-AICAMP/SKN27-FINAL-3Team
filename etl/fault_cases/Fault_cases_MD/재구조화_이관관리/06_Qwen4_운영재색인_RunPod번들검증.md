# 단계 6 Qwen 4B 운영 재색인 RunPod 번들 검증

## 현재 판정

- 상태: **RUNPOD_UPLOAD_READY**
- 단계 6 전체 완료 여부: **미완료**
- 남은 필수 관문: 실제 GPU 임베딩 → tar.gz 수신 검증 → 세 DB staging 적재 → 활성 인덱스 승격

## 실행 계약

| 항목 | 확정값 |
|---|---|
| 실행 ID | `qwen4_operational_20260721_v2` |
| 모델 | `Qwen/Qwen3-Embedding-4B` |
| 모델 리비전 | `5cf2132abc99cad020ac570b19d031efec650f2b` |
| 기본 차원 | `2560` |
| 정규화 | L2 |
| 운영 문서 벡터 dtype | float32 |

## 입력 전수검증 결과

| 코퍼스 | 상위 문서 | 임베딩 단위 | 단계 5 DB ID·입력해시 대조 |
|---|---:|---:|---|
| 인정기준 | 277 | 277 | PASS |
| 심의사례 | 226 | 904 | PASS |
| 판례 | 987 | 8,334 | PASS |

추가로 다음 항목을 확인했다.

- 공통 질문지 50개가 모두 `approved`이고 ID·본문이 유효함
- 인정기준 Complete30 질문·정답이 각각 30개이며 ID와 원본 레코드 해시가 일치함
- 세 코퍼스 qrels가 공통 질문 50개를 덮고 실제 문서·청크 ID를 가리킴
- qrels와 정답지는 RunPod ZIP에 포함하지 않음
- `.env`, API 키, RunPod 키와 DB 비밀번호를 ZIP에 포함하지 않음
- Hugging Face API에서 고정 모델 commit SHA가 실제로 존재하고 일치함

## ZIP 검증 결과

- 파일명: `qwen4_three_corpus_operational_bundle_qwen4_operational_20260721_v2.zip`
- SHA-256: `ac1da0baeba891b589bbf85e57864c7bc14d814f91b19df137602db757bcc518`
- ZIP CRC 검사: PASS
- 내부 Linux `/` 경로 검사: PASS
- 절대경로·`..` 경로 탈출 검사: PASS
- 별도 디렉터리 압축 해제 후 Python import: PASS
- 입력 manifest·파일 SHA-256 재검사: PASS
- Git Bash `bash -n` 셸 문법 검사: PASS
- RunPod 기본 이미지의 구형 `torchvision`·`torchaudio`·`torchtext` 제거 절차 포함: PASS
- `torch==2.7.1`, `transformers==4.54.0`, `numpy==1.26.4` 고정 확인: PASS
- 실제 모델 다운로드 전 `PreTrainedModel`·`SentenceTransformer` import와 CUDA 사전검사 포함: PASS

초기 `v1`은 RunPod 기본 이미지의 `torchvision==0.19.1`·`torchaudio==2.4.1`이 새 `torch==2.7.1`과 섞이면서 `PreTrainedModel` import 단계에서 중단됐다. 임베딩은 시작되지 않았고 운영 산출물도 생성되지 않았다. 공식 PyTorch 2.7.1 릴리스 조합은 torchvision 0.22.1·torchaudio 2.7.1이므로, 텍스트 임베딩에 필요하지 않은 기존 선택 패키지를 제거하는 `v2`로 교체했다. `v1` ZIP과 실행 ID는 재사용하지 않는다.

## 실행기 기능 검증

- 고정 shard 생성·Parquet 저장: PASS
- 같은 실행 ID의 완전한 shard 재개·건너뛰기: PASS
- float32 고정 2,560차원 Arrow 스키마 검사: PASS
- NaN·Inf·L2 norm 전수검사: PASS
- metadata JSON 파싱과 결과 ID 일치 검사: PASS
- 277·904·8,334개 전체 규모의 패키징·안전 해제·체크섬·벡터 전수검사: PASS

전체 규모 전송 통합 검사는 기존 검증 벡터를 **전송 형식 테스트용으로만** 임시 재포장하여 수행했다. 해당 임시 결과는 운영 벡터로 승인하거나 보존하지 않았고 테스트 종료 시 자동 제거했다. 실제 운영 벡터는 아래 RunPod 실행으로 새로 생성해야 한다.

## RunPod 실행 명령

ZIP을 Jupyter의 `/workspace`에 업로드한 뒤 다음 명령을 그대로 실행한다.

```bash
cd /workspace && \
mkdir -p qwen4_operational_stage6 && \
cd qwen4_operational_stage6 && \
python -m zipfile -e ../qwen4_three_corpus_operational_bundle_qwen4_operational_20260721_v2.zip . && \
bash etl/fault_cases/src/shared_embedding/qwen4_operational/runpod_execute_qwen4_three_corpora.sh qwen4_operational_20260721_v2
```

완료 시 생성되어야 하는 파일은 다음 하나다.

```text
/workspace/qwen4_three_corpus_operational_qwen4_operational_20260721_v2.tar.gz
```

이 tar.gz를 로컬로 내려받아 수신 검증기에 전달한다. 로컬 검증을 통과하기 전에는 운영 DB에 적재하지 않는다.
