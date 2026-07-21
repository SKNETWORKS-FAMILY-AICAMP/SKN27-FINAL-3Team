#!/usr/bin/env bash

# 첫 오류·미정의 변수·파이프 내부 오류에서 즉시 중단한다.
set -Eeuo pipefail

# 실행 ID를 필수로 받아 다른 실행 결과가 같은 폴더에 섞이지 않게 한다.
RUN_ID="${1:-}"
if [[ -z "${RUN_ID}" ]]; then
  echo "오류: 실행 ID가 필요합니다. 예: qwen4_operational_20260721_v1" >&2
  exit 1
fi

# 경로·셸 주입을 막기 위해 영문·숫자·밑줄·하이픈만 허용한다.
if [[ ! "${RUN_ID}" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "오류: 실행 ID에는 영문·숫자·밑줄·하이픈만 사용할 수 있습니다." >&2
  exit 1
fi

# 이 셸 파일 위치를 기준으로 ZIP 압축 해제 루트를 계산한다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

# 입력·작업 shard·최종 결과 경로를 실행 ID별로 완전히 분리한다.
INPUT_ROOT="${BUNDLE_ROOT}/runpod_input"
WORK_ROOT="/workspace/qwen4_operational_work_${RUN_ID}"
OUTPUT_ROOT="/workspace/qwen4_operational_result_${RUN_ID}"
ARCHIVE_PATH="/workspace/qwen4_three_corpus_operational_${RUN_ID}.tar.gz"

# 결과 로그 폴더를 의존성 설치 전에 만들어 설치 정보도 함께 회수한다.
mkdir -p "${OUTPUT_ROOT}/logs"

# Python 출력이 파일 버퍼에 머물지 않도록 즉시 터미널과 로그에 표시한다.
export PYTHONUNBUFFERED=1
# tokenizer 병렬 경고와 불필요한 CPU oversubscription을 줄인다.
export TOKENIZERS_PARALLELISM=false
# CUDA allocator 조각화를 줄여 A40·A6000의 장시간 배치 실행을 안정화한다.
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# ZIP 입력과 실행 모듈이 모두 존재하는지 패키지 설치 전에 확인한다.
test -s "${INPUT_ROOT}/input_manifest.json" || {
  echo "오류: runpod_input/input_manifest.json이 없습니다." >&2
  exit 1
}
test -s "${SCRIPT_DIR}/requirements-runpod.txt" || {
  echo "오류: requirements-runpod.txt가 없습니다." >&2
  exit 1
}

# RunPod 기본 이미지의 torchvision·torchaudio는 기존 torch와 한 세트로 설치되어 있을 수 있다.
# 이 작업은 텍스트 임베딩만 사용하므로 두 선택 의존성을 먼저 제거해 새 torch와의 혼용을 차단한다.
python -m pip uninstall -y torchvision torchaudio torchtext \
  2>&1 | tee "${OUTPUT_ROOT}/logs/optional_torch_packages_cleanup.log"

# 고정 의존성을 설치하며 API 키나 `.env`는 읽지 않는다.
python -m pip install --upgrade --no-cache-dir -r "${SCRIPT_DIR}/requirements-runpod.txt" \
  2>&1 | tee "${OUTPUT_ROOT}/logs/dependency_install.log"

# 실제 모델 다운로드 전에 핵심 import·버전·CUDA를 검사해 호환성 오류를 조기에 설명한다.
python - <<'PY' 2>&1 | tee "${OUTPUT_ROOT}/logs/dependency_import_check.log"
import torch  # CUDA 사용 가능 여부와 실제 설치된 PyTorch 버전을 검사한다.
import transformers  # Qwen3 모델 구현을 제공하는 패키지 자체 import를 검사한다.
from transformers import PreTrainedModel  # 기존 torchvision 충돌이 재발하는지 직접 확인한다.
from sentence_transformers import SentenceTransformer  # 실제 임베딩 진입점 import를 확인한다.

if torch.__version__.split("+")[0] != "2.7.1":
    raise RuntimeError(f"PyTorch 고정 버전 불일치: {torch.__version__}")
if transformers.__version__ != "4.54.0":
    raise RuntimeError(f"Transformers 고정 버전 불일치: {transformers.__version__}")
if not torch.cuda.is_available():
    raise RuntimeError("CUDA GPU를 사용할 수 없습니다.")

print(f"의존성 import 검증 완료: torch={torch.__version__}, transformers={transformers.__version__}")
print(f"CUDA 검증 완료: {torch.cuda.get_device_name(0)}")
PY

# 세 코퍼스와 평가 질문을 순차 실행하고 중단 시 shard 기준으로 재개한다.
python -m etl.fault_cases.src.shared_embedding.qwen4_operational.run_qwen4_three_corpora \
  run \
  --run-id "${RUN_ID}" \
  --input-root "${INPUT_ROOT}" \
  --output-root "${OUTPUT_ROOT}" \
  --work-root "${WORK_ROOT}" \
  --batch-size 32 \
  --shard-size 128 \
  2>&1 | tee "${OUTPUT_ROOT}/logs/runpod_execution.log"

# 위 실행과 전체 검증이 성공한 경우에만 최종 tar.gz를 생성한다.
python -m etl.fault_cases.src.shared_embedding.qwen4_operational.run_qwen4_three_corpora \
  package \
  --run-id "${RUN_ID}" \
  --output-root "${OUTPUT_ROOT}" \
  --archive-path "${ARCHIVE_PATH}" \
  2>&1 | tee -a "${OUTPUT_ROOT}/logs/runpod_execution.log"

# 사용자에게 다운로드할 유일한 결과 파일과 다음 행동을 명확히 안내한다.
echo "완료: ${ARCHIVE_PATH}"
echo "이 tar.gz를 다운로드해 Codex에 전달한 뒤 Pod를 Stop하세요."
