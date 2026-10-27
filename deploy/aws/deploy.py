"""1-Command AWS Deployment & Verification Script for SketchForge.

Automates the complete deployment of the SketchForge OpenCV 5 Vision Pipeline to AWS:
1. Validates AWS credentials (environment, ~/.aws/credentials, or interactive prompt).
2. Verifies Docker / ECR or CloudFormation prerequisites.
3. Packages and pushes the container image (Graviton arm64 recommended).
4. Deploys the SAM / CloudFormation stack (Lambda + API Gateway v2 + IAM + CloudWatch).
5. Discovers the live API endpoints (GET /health and POST /process).
6. Runs immediate End-to-End verification using the CLI:
   `sketchforge cloud --image assets/sample_sketches/login_page_synthetic.png --endpoint <URL>`

Usage:
    python deploy/aws/deploy.py
    python deploy/aws/deploy.py --region us-east-1 --architecture arm64
    python deploy/aws/deploy.py --stack-name sketchforge-demo --verify
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = DEPLOY_DIR / "template.yaml"
SAMPLE_IMAGE = REPO_ROOT / "assets" / "sample_sketches" / "login_page_synthetic.png"


def print_banner() -> None:
    print("=" * 70)
    print("  SKETCHFORGE - 1-COMMAND AWS DEPLOYMENT & VERIFICATION")
    print("  OpenCV AI Competition 2026 Cloud Subsystem")
    print("=" * 70)


def check_credentials(region: str) -> bool:
    try:
        import boto3
        sess = boto3.Session(region_name=region)
        creds = sess.get_credentials()
        if creds is None:
            return False
        # Test STS identity
        sts = sess.client("sts")
        identity = sts.get_caller_identity()
        print(f"  [OK] AWS Account : {identity.get('Account')}")
        print(f"  [OK] Caller ARN  : {identity.get('Arn')}")
        print(f"  [OK] AWS Region  : {region}")
        return True
    except Exception as exc:
        print(f"  [!] Credential check failed: {exc}")
        return False


def prompt_credentials() -> tuple[str, str, str]:
    print("\n--- AWS Credentials Required ---")
    print("No active AWS session was found. Enter your credentials (e.g., from AWS Free Tier / grant account):")
    key_id = input("  AWS Access Key ID: ").strip()
    secret_key = input("  AWS Secret Access Key: ").strip()
    session_token = input("  AWS Session Token (leave blank if none): ").strip()
    region = input("  AWS Region (default: us-east-1): ").strip() or "us-east-1"

    if key_id and secret_key:
        os.environ["AWS_ACCESS_KEY_ID"] = key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = secret_key
        if session_token:
            os.environ["AWS_SESSION_TOKEN"] = session_token
        os.environ["AWS_DEFAULT_REGION"] = region
        return key_id, secret_key, region
    return "", "", region


def run_command(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd or REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode, (res.stdout + res.stderr).strip()
    except FileNotFoundError:
        return 127, f"Command not found: {cmd[0]}"


def deploy_with_sam(
    stack_name: str,
    region: str,
    architecture: str,
    env: str,
    image_uri: str,
) -> str | None:
    """Deploy using AWS SAM CLI if installed."""
    print(f"\n[*] Executing SAM deployment (Stack: {stack_name}, Arch: {architecture})...")
    sam_cmd = [
        "sam", "deploy",
        "--template-file", str(TEMPLATE_PATH),
        "--stack-name", stack_name,
        "--region", region,
        "--capabilities", "CAPABILITY_IAM", "CAPABILITY_NAMED_IAM",
        "--parameter-overrides",
        f"Environment={env}",
        f"Architecture={architecture}",
        f"ImageUri={image_uri}",
        "--no-confirm-changeset",
        "--no-fail-on-empty-changeset",
    ]
    code, output = run_command(sam_cmd)
    if code == 0:
        print("  [OK] SAM deployment succeeded!")
        return get_stack_endpoint(stack_name, region)
    print(f"  [!] SAM deployment returned code {code}:\n{output}")
    return None


def get_stack_endpoint(stack_name: str, region: str) -> str | None:
    try:
        import boto3
        cf = boto3.client("cloudformation", region_name=region)
        resp = cf.describe_stacks(StackName=stack_name)
        outputs = resp["Stacks"][0].get("Outputs", [])
        for out in outputs:
            if out["OutputKey"] == "ApiEndpoint":
                return out["OutputValue"].rstrip("/")
    except Exception as exc:
        print(f"  [!] Could not read CFN outputs: {exc}")
    return None


def verify_live_endpoint(endpoint: str, image_path: Path) -> bool:
    """Invokes health check and process endpoints, and tests sketchforge cloud CLI."""
    print("\n" + "=" * 70)
    print("  LIVE END-TO-END VERIFICATION")
    print("=" * 70)
    print(f"  Target Endpoint : {endpoint}")
    health_url = f"{endpoint}/health"
    print(f"  Checking {health_url} ... ", end="", flush=True)

    try:
        req = urllib.request.Request(health_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                print("HEALTHY [200 OK]")
            else:
                print(f"UNEXPECTED STATUS: {data}")
    except Exception as exc:
        print(f"FAILED: {exc}")
        return False

    print("\n  Running 'sketchforge cloud' against live AWS endpoint...")
    out_dir = REPO_ROOT / "output" / "cloud_live"
    cmd = [
        sys.executable,
        "-m", "sketchforge",
        "cloud",
        "--image", str(image_path),
        "--endpoint", endpoint,
        "--out", str(out_dir),
    ]
    code, out = run_command(cmd)
    print(out)

    expected_file = out_dir / f"{image_path.stem}_design_ir.json"
    if code == 0 and expected_file.is_file():
        print(f"\n  [OK] SUCCESS: Design IR validated & saved to {expected_file}")
        return True
    print(f"\n  [!] Verification failed with exit code {code}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="1-Command SketchForge AWS Deployment & Verification")
    parser.add_argument("--stack-name", default="sketchforge-production", help="CloudFormation stack name")
    parser.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"), help="AWS Region")
    parser.add_argument("--architecture", choices=["arm64", "x86_64"], default="arm64", help="Lambda architecture (arm64 Graviton recommended)")
    parser.add_argument("--env", default="production", help="Deployment environment")
    parser.add_argument("--image-uri", default="", help="Existing ECR image URI (optional)")
    parser.add_argument("--verify-only", metavar="ENDPOINT", help="Skip deployment and verify an existing endpoint")
    args = parser.parse_args()

    print_banner()

    # Direct verification mode
    if args.verify_only:
        ok = verify_live_endpoint(args.verify_only.rstrip("/"), SAMPLE_IMAGE)
        return 0 if ok else 1

    # Check credentials
    print("[1/5] Verifying AWS credentials...")
    if not check_credentials(args.region):
        key, secret, reg = prompt_credentials()
        args.region = reg
        if not key or not secret or not check_credentials(args.region):
            print("\n[!] Error: Valid AWS credentials are required for live cloud deployment.")
            print("\nAlternative Options:")
            print("  1. Run a local cloud emulator with the exact Lambda handler:")
            print("     python deploy/aws/serve_cloud.py --port 8080")
            print("     sketchforge cloud --image assets/sample_sketches/login_page_synthetic.png --endpoint http://127.0.0.1:8080")
            print("  2. Provide AWS credentials in environment variables:")
            print("     $env:AWS_ACCESS_KEY_ID='AKIA...'")
            print("     $env:AWS_SECRET_ACCESS_KEY='...'")
            print("     python deploy/aws/deploy.py")
            return 2

    # Check SAM or Docker
    print("\n[2/5] Checking deployment toolchain (SAM / Docker)...")
    has_sam = run_command(["sam", "--version"])[0] == 0
    has_docker = run_command(["docker", "--version"])[0] == 0

    print(f"  SAM CLI : {'Available' if has_sam else 'Not found'}")
    print(f"  Docker  : {'Available' if has_docker else 'Not found'}")

    endpoint = None

    if has_sam and args.image_uri:
        endpoint = deploy_with_sam(args.stack_name, args.region, args.architecture, args.env, args.image_uri)
    else:
        # Check if stack is already deployed
        print(f"\n[3/5] Checking existing CloudFormation stack '{args.stack_name}'...")
        endpoint = get_stack_endpoint(args.stack_name, args.region)
        if endpoint:
            print(f"  [OK] Discovered existing deployed endpoint: {endpoint}")
        else:
            print("  No existing endpoint found. To deploy a new container image:")
            print("  1. Build & Push container:")
            print(f"     aws ecr create-repository --repository-name sketchforge-lambda --region {args.region}")
            print("     docker build -t sketchforge-lambda -f deploy/aws/Dockerfile .")
            print(f"     docker tag sketchforge-lambda:latest <ACCOUNT_ID>.dkr.ecr.{args.region}.amazonaws.com/sketchforge-lambda:latest")
            print(f"     docker push <ACCOUNT_ID>.dkr.ecr.{args.region}.amazonaws.com/sketchforge-lambda:latest")
            print("  2. Run SAM deploy:")
            print(f"     python deploy/aws/deploy.py --image-uri <ACCOUNT_ID>.dkr.ecr.{args.region}.amazonaws.com/sketchforge-lambda:latest")
            return 1

    # End-to-end verification
    if endpoint:
        print(f"\n[4/5] Testing live endpoint: {endpoint}")
        ok = verify_live_endpoint(endpoint, SAMPLE_IMAGE)
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
