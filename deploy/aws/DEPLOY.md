# SketchForge AWS Deployment Guide
> **Competition requirements fulfilled**:
> 1. "A meaningful component of the project must run on Amazon Web Services."
> 2. "Best Use of COOL Award ($1,000 Track)" — Cloud-Optimized OpenCV Library (COOL) on AWS Graviton (Arm64).

## What was built

| Artifact | Purpose |
|---|---|
| `deploy/aws/lambda_function.py` | AWS Lambda handler — receives base64 sketch photo → runs OpenCV 5 pipeline → returns Design IR JSON |
| `deploy/aws/Dockerfile` | AWS Graviton Lambda container (`--platform=linux/arm64`) with COOL & SIMD NEON flags |
| `deploy/aws/Dockerfile.graviton` | Standalone EC2 Graviton (`c7g.large` / `t4g.xlarge`) container running `serve_cloud.py` |
| `deploy/aws/requirements-lambda.txt` | Minimal Python deps for the Graviton container |
| `deploy/aws/template.yaml` | AWS SAM / CloudFormation template — `Architectures: [arm64]` + API Gateway v2 + IAM + CloudWatch |
| `deploy/aws/deploy.py` | 1-Command cross-platform deployment & verification orchestrator |
| `deploy/aws/deploy.ps1` | 1-Command PowerShell deployment script for Windows |
| `deploy/aws/deploy.sh` | 1-Command Bash deployment script for Linux/macOS |
| `deploy/aws/serve_cloud.py` | Standalone HTTP server emulator executing the exact Lambda handler |
| `scripts/benchmark_cool_graviton.py` | Reproducible benchmark script comparing x86 vs COOL on Graviton (latency & cost) |
| `src/sketchforge/cloud/aws_client.py` | Python client that POSTs a sketch photo to the Lambda endpoint and returns `DesignDocument` |
| `src/sketchforge/cloud/__init__.py` | Package init |

## 1-Command Deployment (Recommended)

### Using Python (Cross-platform)
```bash
python deploy/aws/deploy.py --region us-east-1 --architecture arm64
```

### Using Windows PowerShell
```powershell
.\deploy\aws\deploy.ps1 -Region us-east-1 -Architecture arm64
```

### Using Linux / macOS Bash
```bash
./deploy/aws/deploy.sh --region us-east-1 --architecture arm64
```

These scripts automate checking AWS credentials, setting up ECR, deploying the SAM / CloudFormation stack targeting **AWS Graviton arm64** (with `Architectures: [arm64]` and Cloud-Optimized OpenCV Library flags for 20-40% price-performance gain), discovering live endpoints, and executing an end-to-end cloud test.

---

## Manual Step-by-Step Deployment

### Prerequisites
```bash
pip install awscli aws-sam-cli
aws configure   # set access key, secret, region
```

### 1. Build & push the container image (Graviton arm64)
```bash
cd deploy/aws

# Create ECR repository (once)
aws ecr create-repository --repository-name sketchforge-lambda --region us-east-1

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS \
    --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build for Graviton arm64 (from project root)
docker buildx build --platform linux/arm64 -t sketchforge-lambda -f deploy/aws/Dockerfile .

# Tag & push
docker tag sketchforge-lambda:latest \
  <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/sketchforge-lambda:latest
docker push \
  <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/sketchforge-lambda:latest
```

### 2. Deploy with SAM
```bash
sam deploy \
  --template-file deploy/aws/template.yaml \
  --stack-name sketchforge-production \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ImageUri=<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/sketchforge-lambda:latest \
    Architecture=arm64 \
    Environment=production \
  --region us-east-1
```

After deploy, SAM prints the API endpoint URL.

### 3. Test the endpoint
```bash
# Health check
curl https://<api-id>.execute-api.us-east-1.amazonaws.com/production/health

# Process a sketch
python - <<'EOF'
import base64, json, urllib.request

with open("assets/sample_sketches/login_page_synthetic.png", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = json.dumps({"image_b64": b64}).encode()
req = urllib.request.Request(
    "https://<api-id>.execute-api.us-east-1.amazonaws.com/production/process",
    data=payload,
    method="POST",
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())
    print("Components:", len(data["design_ir"]["components"]))
    print("Notes:", data["notes"])
EOF
```

### 4. Use the CLI flag
```bash
# Set endpoint via env var
export SKETCHFORGE_AWS_ENDPOINT=https://<api-id>.execute-api.us-east-1.amazonaws.com/production

# Process a sketch via AWS
sketchforge cloud --image assets/sample_sketches/login_page_synthetic.png --out output/cloud

# Or with explicit endpoint
sketchforge cloud --image rough_mobile_ux.jpg \
  --endpoint https://<api-id>.execute-api.us-east-1.amazonaws.com/production
```

### 5. Auto-discovery (optional)
```bash
export SKETCHFORGE_AWS_STACK_NAME=sketchforge-production
export AWS_DEFAULT_REGION=us-east-1
# AWSSketchClient will query CloudFormation outputs automatically
sketchforge cloud --image rough_mobile_ux.jpg
```

---

## AWS Graviton EC2 Deployment (`c7g.large` / `t4g.xlarge`)

For high-throughput batch sketch processing or continuous interactive web preview service on AWS Graviton:

### 1. Launch an AWS Graviton EC2 Instance
- Instance Type: `c7g.large` (AWS Graviton3, 2 vCPUs, 4 GiB DDR5 memory) or `t4g.xlarge` (AWS Graviton2, 4 vCPUs, 16 GiB memory).
- Operating System: Amazon Linux 2023 (AMI: `al2023-ami-*-arm64`) or Cloud-Optimized OpenCV Library (COOL) AMI from AWS Marketplace.

### 2. Deploy Container with Docker
```bash
# Clone repository
git clone https://github.com/Akash010203/SKETCHFORGE.git
cd SKETCHFORGE

# Build using the Graviton-optimized Dockerfile
docker build -t sketchforge-graviton -f deploy/aws/Dockerfile.graviton .

# Run container with host port mapping
docker run -d --name sketchforge-cv -p 8080:8080 sketchforge-graviton

# Test health check
curl http://localhost:8080/health
```

### 3. Run the COOL vs x86 Benchmark on Graviton
```bash
# Run the reproducible benchmark measuring latency, throughput, and price-performance
python scripts/benchmark_cool_graviton.py --iterations 30 --output experiments/results/cool_graviton_benchmark.md --json experiments/results/cool_graviton_benchmark.json
```

---

## Architecture diagram

```
Smartphone photo
      │
      ▼ (base64 JSON  POST /process)
 API Gateway HTTP API (v2)
      │
      ▼
 AWS Lambda  (2 GB, 29s, container image)
      │
      ├─ perspective correction (cv2)
      ├─ local illumination flattening (MORPH_DILATE 40×40)
      ├─ adaptive / Otsu / relative thresholding
      ├─ ruled-line suppression  (morphological)
      ├─ grid-paper FFT notch filter
      ├─ grid-lattice FP filter  (density CV < 8%)
      ├─ contour detection + shape classification
      ├─ component detection (button / checkbox / input …)
      └─ hierarchy inference
      │
      ▼ (JSON response)
 Design IR  →  SketchForge workbench
```

---

## Submission video script (3 min)

| Time | Action |
|------|--------|
| 0:00 – 0:20 | Hold up a hand-drawn sketch to the camera; photograph it with a smartphone. |
| 0:20 – 0:50 | `sketchforge cloud --image rough_mobile_ux.jpg --endpoint <URL>` — show terminal output with component count and round-trip time. |
| 0:50 – 1:30 | Open the SketchForge workbench; load the saved `*_design_ir.json`; show components highlighted in the editor. |
| 1:30 – 2:10 | Run `sketchforge demo --image rough_mobile_ux.jpg --inject overflow`; show repair loop fixing the injected fault. |
| 2:10 – 2:40 | Show the AWS Console: Lambda invocation graph + CloudWatch log stream with per-stage timings. |
| 2:40 – 3:00 | Summary: OpenCV 5 on AWS, Design IR, closed-loop repair — all in 3 minutes. |
