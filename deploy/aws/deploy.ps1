<#
.SYNOPSIS
    1-Command AWS Deployment & Verification Script for SketchForge (Windows PowerShell).
.DESCRIPTION
    Automates building, deploying, and testing the SketchForge OpenCV 5 Vision Pipeline on AWS.
.EXAMPLE
    .\deploy\aws\deploy.ps1
    .\deploy\aws\deploy.ps1 -Region us-east-1 -Architecture arm64
#>

param(
    [string]$StackName = "sketchforge-production",
    [string]$Region = "us-east-1",
    [string]$Architecture = "arm64",
    [string]$Environment = "production",
    [string]$ImageUri = "",
    [string]$VerifyOnly = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location $RepoRoot

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  SKETCHFORGE - 1-COMMAND AWS DEPLOYMENT & VERIFICATION (PowerShell)  " -ForegroundColor Cyan
Write-Host "  OpenCV AI Competition 2026 Cloud Subsystem                          " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

if ($VerifyOnly -ne "") {
    Write-Host "`n[*] Verifying live endpoint: $VerifyOnly" -ForegroundColor Yellow
    python -m sketchforge cloud --image assets/sample_sketches/login_page_synthetic.png --endpoint $VerifyOnly --out output/cloud_live
    exit $LASTEXITCODE
}

# 1. Run Python deployment orchestrator
Write-Host "`n[1/3] Launching AWS Deployment Manager..." -ForegroundColor Green
$cmdArgs = @("deploy/aws/deploy.py", "--stack-name", $StackName, "--region", $Region, "--architecture", $Architecture, "--env", $Environment)
if ($ImageUri -ne "") {
    $cmdArgs += @("--image-uri", $ImageUri)
}

python @cmdArgs
exit $LASTEXITCODE
