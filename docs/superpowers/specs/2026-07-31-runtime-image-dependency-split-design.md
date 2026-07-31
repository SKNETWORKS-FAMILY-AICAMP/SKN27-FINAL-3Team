# Runtime Image Dependency Split Design

## Goal

Keep the Pilot backend image free of local ML and GPU dependency trees while preserving the existing OpenAI RAG, RunPod Vision, and optional local embedding workflows.

## Context

The deployed backend image is approximately 6.37 GB. Its runtime dependency set installs `sentence-transformers`, which pulls PyTorch and CUDA packages even though the live Pilot uses OpenAI embeddings. Repeated release and rollback images exhausted the EC2 root disk and caused the immutable-image deployment to fail while downloading a new backend image.

## Architecture

### Production runtime boundary

- `requirements.txt` remains the default application dependency file and contains only packages required by the Django API, workers, OpenAI-backed RAG, database access, document processing, and browser/OCR integrations.
- It must not contain `sentence-transformers`, `transformers`, `torch`, `torchvision`, `ultralytics`, OpenCV, or other local model inference packages.
- The root `Dockerfile` continues to install only `requirements.txt`; no model packages, model caches, or GPU libraries are copied into the backend image.
- No runtime provider setting changes. The current OpenAI embedding configuration continues unchanged. If an operator selects a local sentence-transformers provider in production, the existing readiness validation must fail with its explicit missing-dependency diagnosis instead of silently downloading a model.

### Optional local embedding boundary

- Create `requirements-local-embedding.txt` for developer and ETL-only local embedding experiments.
- It includes `-r requirements.txt` and pins the currently supported `sentence-transformers==5.5.1` and `transformers==4.57.6` dependencies.
- No Docker deployment or CodePipeline production build installs this optional file.

### Vision boundary

- `requirements-vision-runpod.txt` and `deploy/runpod-vision/Dockerfile` remain the RunPod Vision runtime path.
- `deploy/aws-vision/Dockerfile` and `deploy/aws-vision/requirements.txt` remain the separately built, opt-in AWS Vision worker path. The immutable-image build script builds that image only when `VISION_REPOSITORY_URI` is configured.
- Both Vision images continue to use their own PyTorch CUDA base image and are built/pushed independently from the Pilot backend image.
- RunPod adapter behavior, endpoint configuration, AWS GPU activation, and user uploads are out of scope for this dependency-only change.

## Safety and rollback

- The production image no longer needs a local-model rollback artifact. Existing release rollback snapshots remain unchanged and still use the image currently running at deployment start.
- The first deployment after this change can pull a new smaller backend image after unused image cleanup. It must still retain enough free disk space for the current image and one rollback image.
- No RDS, pgvector, Neo4j, RAG seed, Docker volume, or runtime secret is modified.

## Verification

### Offline dependency checks

- Add a focused test that asserts the production requirements and root Dockerfile do not include local inference packages.
- Add a focused test that asserts the optional local-embedding file inherits the runtime requirements and declares the supported local embedding libraries.
- Run the existing readiness and Pilot infrastructure contract tests to confirm OpenAI runtime behavior and deployment configuration remain valid.
- Build the runtime image locally or in CodeBuild and record its image size. The acceptance threshold is that the backend image is materially smaller than the current 6.37 GB image and has no PyTorch/CUDA package layers.

### End-to-end checks

- Run the canonical Django E2E suite for guest-session ownership, conversation routing, supervisor reporting, and objection-report handoff.
- After the dependency PR is deployed, verify the public live and ready endpoints, then run a non-sensitive guest-session flow covering general, fine-notice, and fault-ratio intake routing.
- The fault-ratio check verifies that the correct agent path is selected and that unavailable review-case or new-chunk data is reported as a concrete limitation rather than a blank response. It does not treat an unimplemented new-chunk corpus as a valid precedent result.
- Google OAuth remains a manual browser check because it requires an interactive account session. RunPod Vision remains an adapter-contract check because this change must not start a paid remote GPU workload.

## Non-goals

- Changing the selected RAG embedding model or re-embedding data.
- Activating the AWS Vision GPU worker or RunPod endpoint.
- Removing active containers, volumes, RAG data, or the currently running deployment.
