FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/vision-volume/huggingface

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-vision-runpod.txt /tmp/requirements-vision.txt
COPY deploy/aws-vision/requirements.txt /tmp/requirements-aws-vision.txt
RUN python -m pip install --no-cache-dir \
    -r /tmp/requirements-vision.txt \
    -r /tmp/requirements-aws-vision.txt

COPY ai /workspace/ai
COPY app /workspace/app

CMD ["sh", "-c", "python -u -m app.services.aws_vision_worker"]
