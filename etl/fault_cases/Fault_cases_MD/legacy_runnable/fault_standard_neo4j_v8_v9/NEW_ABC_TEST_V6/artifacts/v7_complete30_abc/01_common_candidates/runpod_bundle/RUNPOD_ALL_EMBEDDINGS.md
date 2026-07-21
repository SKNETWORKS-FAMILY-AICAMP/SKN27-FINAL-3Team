# Complete30 Qwen 4B GPU embedding bundle

This bundle creates every vector required for the V7 ABC evaluation: 277 fixed
인정기준 Rule documents and 30 detailed consumer accident questions.

Use a CUDA-enabled PyTorch RunPod image, upload and unzip this bundle, then:

```bash
cd runpod_bundle
pip install -r requirements.txt
python runpod_encode_all.py
```

Return both generated files without edits:

```text
qwen3_4b_complete30_all_embeddings_v1.jsonl.gz
qwen3_4b_complete30_all_embeddings_manifest.json
```

The program rejects a CPU pod, a corpus other than 277 Rules, a question set
other than 30, non-2,560-dimensional vectors, and non-normalized vectors.
