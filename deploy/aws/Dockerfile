# SketchForge – AWS Lambda Graviton (arm64) container image
# Optimized for AWS Graviton (Neoverse V1/N1) and Cloud-Optimized OpenCV Library (COOL).
#
# Build for AWS Graviton (arm64):
#   docker buildx build --platform linux/arm64 -t sketchforge-lambda -f deploy/aws/Dockerfile .
#
# Build on AWS EC2 Graviton instance (c7g.large / t4g.xlarge):
#   docker build -t sketchforge-lambda -f deploy/aws/Dockerfile .
#
# Push to ECR (Graviton arm64):
#   aws ecr get-login-password --region us-east-1 | docker login --username AWS \
#       --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
#   docker tag sketchforge-lambda:latest ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/sketchforge-lambda:latest
#   docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/sketchforge-lambda:latest

FROM --platform=linux/arm64 public.ecr.aws/lambda/python:3.11

# ---------------------------------------------------------------------------
# 1. System-level build dependencies for OpenCV & COOL on Graviton (arm64)
#    - libgomp: OpenMP multi-threading runtime for parallel CV kernels
#    - openblas-devel: Arm NEON-vectorized linear algebra acceleration
#    - mesa-libGL: GL runtime for image decoding
# ---------------------------------------------------------------------------
RUN dnf install -y --setopt=install_weak_deps=False \
        libgomp \
        openblas-devel \
        mesa-libGL \
    && dnf clean all

# ---------------------------------------------------------------------------
# 2. Performance & SIMD Environment flags for Graviton Neoverse + COOL
# ---------------------------------------------------------------------------
ENV OPENCV_FOR_ARM=1 \
    COOL_OPTIMIZED=1 \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# 3. Python dependencies
#    Pinned opencv-python-headless>=5.0.0 or COOL (Cloud-Optimized OpenCV Library)
# ---------------------------------------------------------------------------
COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt

# ---------------------------------------------------------------------------
# 4. SketchForge source package
# ---------------------------------------------------------------------------
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY pyproject.toml ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir --no-deps ${LAMBDA_TASK_ROOT}/

# ---------------------------------------------------------------------------
# 5. Lambda handler
# ---------------------------------------------------------------------------
COPY deploy/aws/lambda_function.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
