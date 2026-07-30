#!/usr/bin/env bash
set -euo pipefail

for required in AWS_DEFAULT_REGION BACKEND_REPOSITORY_URL FRONTEND_REPOSITORY_URL CODEBUILD_RESOLVED_SOURCE_VERSION; do
  if [[ -z "${!required:-}" ]]; then
    echo "Missing required environment variable: $required" >&2
    exit 2
  fi
done

IMAGE_TAG="${CODEBUILD_RESOLVED_SOURCE_VERSION:0:12}"
if [[ ! "$IMAGE_TAG" =~ ^[0-9a-f]{12}$ ]]; then
  echo "Expected a 12-character lowercase Git commit tag, got: $IMAGE_TAG" >&2
  exit 2
fi

ECR_REGISTRY="${BACKEND_REPOSITORY_URL%%/*}"
aws ecr get-login-password --region "$AWS_DEFAULT_REGION" |
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

image_exists() {
  local image_uri="$1"
  local repository_name="${image_uri#*/}"
  local lookup_error

  if lookup_error="$(aws ecr describe-images \
    --region "$AWS_DEFAULT_REGION" \
    --repository-name "$repository_name" \
    --image-ids "imageTag=$IMAGE_TAG" 2>&1)"; then
    return 0
  fi

  if grep -Fq "ImageNotFoundException" <<<"$lookup_error"; then
    return 1
  fi

  echo "Unable to determine immutable image state for $image_uri:$IMAGE_TAG." >&2
  echo "$lookup_error" >&2
  exit 2
}

if image_exists "$BACKEND_REPOSITORY_URL"; then
  echo "Skipping existing immutable image: $BACKEND_REPOSITORY_URL:$IMAGE_TAG"
else
  docker build --platform linux/amd64 -f Dockerfile -t "$BACKEND_REPOSITORY_URL:$IMAGE_TAG" .
  docker push "$BACKEND_REPOSITORY_URL:$IMAGE_TAG"
fi

if image_exists "$FRONTEND_REPOSITORY_URL"; then
  echo "Skipping existing immutable image: $FRONTEND_REPOSITORY_URL:$IMAGE_TAG"
else
  docker build --platform linux/amd64 \
    -f deploy/aws-pilot/Dockerfile.frontend \
    --build-arg "VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID:-}" \
    -t "$FRONTEND_REPOSITORY_URL:$IMAGE_TAG" .
  docker push "$FRONTEND_REPOSITORY_URL:$IMAGE_TAG"
fi

if test -n "${VISION_REPOSITORY_URI:-}"; then
  if image_exists "$VISION_REPOSITORY_URI"; then
    echo "Skipping existing immutable image: $VISION_REPOSITORY_URI:$IMAGE_TAG"
  else
    docker build --platform linux/amd64 \
      -f deploy/aws-vision/Dockerfile \
      -t "$VISION_REPOSITORY_URI:$IMAGE_TAG" .
    docker push "$VISION_REPOSITORY_URI:$IMAGE_TAG"
  fi
fi
