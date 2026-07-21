# V7 Complete30 Qwen GPU embedding

이 bundle은 **상세 사고 30개 질문의 query vector만** 생성합니다. 277개 Rule document vector는 로컬의 고정 Qwen 4B artifact를 그대로 사용하므로 RunPod에서 다시 만들지 않습니다.

## RunPod 실행

```bash
cd runpod_bundle
pip install -r requirements.txt
python runpod_encode_complete30.py
```

GPU가 잡힌 RunPod 환경에서 실행해야 합니다. 성공하면 다음 두 파일을 로컬의 이 폴더로 다시 가져옵니다.

```text
query_embeddings.parquet
runpod_query_embedding_manifest.json
```

## 변경 금지 계약

- model: `Qwen/Qwen3-Embedding-4B`
- revision: `5cf2132abc99cad020ac570b19d031efec650f2b`
- dimension: `2560`
- normalization: L2
- query instruction: script 상수 그대로
- input: `complete30_consumer_questions_v1.jsonl` 30건

output을 가져온 뒤 Codex가 SHA·행 수·차원·정규화·input hash를 검증하고 A/B/C를 계속 실행합니다.
