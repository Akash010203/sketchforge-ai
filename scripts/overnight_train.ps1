# =============================================================================
# SketchForge — Overnight Training Launcher
# Hardware: RTX 4050 Laptop (6.4 GB VRAM) | 16 GB RAM
# Usage:    Right-click → "Run with PowerShell"
#           OR: powershell -ExecutionPolicy Bypass -File scripts\overnight_train.ps1
# =============================================================================

$ROOT       = Split-Path $PSScriptRoot -Parent
$CONFIG     = "$ROOT\config\overnight_train.yaml"
$SCRIPT     = "$ROOT\scripts\train_component_detector.py"
$LOG_DIR    = "$ROOT\experiments\logs"
$TIMESTAMP  = Get-Date -Format "yyyy-MM-dd_HH-mm"
$LOG_FILE   = "$LOG_DIR\overnight_$TIMESTAMP.log"
$PROG_FILE  = "$ROOT\experiments\overnight_progress.txt"
$MAX_RESTARTS = 3   # auto-restart on crash up to this many times

# ── Setup ────────────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null
New-Item -ItemType Directory -Force -Path "$ROOT\experiments\results" | Out-Null

# ── Helper: write to log AND console ─────────────────────────────────────────
function Log($msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

# ── GPU Power: prefer max performance while plugged in ───────────────────────
Log "=== SketchForge Overnight Training Launcher ==="
Log "Root:       $ROOT"
Log "Config:     $CONFIG"
Log "Log file:   $LOG_FILE"
Log "Max auto-restarts: $MAX_RESTARTS"
Log ""

# Check if plugged in
$powerStatus = (Get-WmiObject -Class Win32_Battery).BatteryStatus
if ($powerStatus -ne 2) {
    Log "WARNING: Laptop may not be plugged in! Battery status = $powerStatus"
    Log "         Please plug in your charger before leaving overnight."
    Start-Sleep -Seconds 5
}

# ── Pre-flight checks ────────────────────────────────────────────────────────
Log "--- Pre-flight checks ---"

# Check Python
try {
    $pyVer = python --version 2>&1
    Log "Python: $pyVer"
} catch {
    Log "ERROR: Python not found. Aborting."
    Read-Host "Press Enter to exit"
    exit 1
}

# Check CUDA
$cudaCheck = python -c "import torch; print('CUDA OK' if torch.cuda.is_available() else 'NO CUDA')" 2>&1
Log "PyTorch CUDA: $cudaCheck"

# Check config exists
if (-not (Test-Path $CONFIG)) {
    Log "ERROR: Config not found at $CONFIG"
    Read-Host "Press Enter to exit"
    exit 1
}

# Check data exists — auto-generate synthetic data if not enough labeled samples
$syntheticDir = "$ROOT\datasets\synthetic"
$MIN_IMAGES = 2000
if (Test-Path $syntheticDir) {
    $imgCount = (Get-ChildItem -Path $syntheticDir -Filter "*.png" -ErrorAction SilentlyContinue).Count
} else {
    $imgCount = 0
}
Log "Synthetic dataset: $imgCount labeled PNG files found (minimum needed: $MIN_IMAGES)"

if ($imgCount -lt $MIN_IMAGES) {
    $needed = 5000
    Log ""
    Log "==> Not enough labeled training data. Auto-generating $needed synthetic sketches..."
    Log "    (This takes ~15-20 minutes. Do NOT close this window.)"
    Log ""
    & python "$ROOT\scripts\generate_synthetic_data.py" --count $needed --seed 1 --out "$ROOT\datasets\synthetic" 2>&1 | Tee-Object -Append $LOG_FILE
    $imgCount = (Get-ChildItem -Path $syntheticDir -Filter "*.png" -ErrorAction SilentlyContinue).Count
    Log "Generated. Now have $imgCount labeled PNG files."
} else {
    Log "Sufficient labeled data found. Skipping generation."
}

Log ""
Log "=== Starting training in 5 seconds... ==="
Log "    Press Ctrl+C NOW to cancel."
Log ""
Start-Sleep -Seconds 5

# ── Training Loop with auto-restart ─────────────────────────────────────────
$attempt   = 0
$exitCode  = 1

while ($attempt -le $MAX_RESTARTS -and $exitCode -ne 0) {
    $attempt++
    Log ""
    Log ">>> TRAINING ATTEMPT $attempt of $($MAX_RESTARTS + 1) <<<"
    Log ""

    # Write progress marker
    "Attempt $attempt | Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Set-Content $PROG_FILE

    # Run training — output goes to console AND log file simultaneously
    $proc = Start-Process python `
        -ArgumentList "-I `"$SCRIPT`" --config `"$CONFIG`"" `
        -WorkingDirectory $ROOT `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput "$LOG_DIR\stdout_$TIMESTAMP`_attempt$attempt.txt" `
        -RedirectStandardError  "$LOG_DIR\stderr_$TIMESTAMP`_attempt$attempt.txt"

    Log "Training PID: $($proc.Id)"

    # Stream stdout to console while training runs
    $stdoutFile = "$LOG_DIR\stdout_$TIMESTAMP`_attempt$attempt.txt"
    $lastLine   = 0
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 3
        if (Test-Path $stdoutFile) {
            $lines = Get-Content $stdoutFile
            if ($lines.Count -gt $lastLine) {
                $lines[$lastLine..($lines.Count - 1)] | ForEach-Object { Write-Host $_ }
                $lastLine = $lines.Count
            }
        }
    }
    # Flush remaining output
    if (Test-Path $stdoutFile) {
        $lines = Get-Content $stdoutFile
        if ($lines.Count -gt $lastLine) {
            $lines[$lastLine..($lines.Count - 1)] | ForEach-Object { Write-Host $_ }
        }
    }

    $exitCode = $proc.ExitCode
    Log ""
    Log "Training attempt $attempt finished — exit code: $exitCode"

    if ($exitCode -eq 0) {
        Log "SUCCESS: Training completed normally."
        break
    } elseif ($attempt -le $MAX_RESTARTS) {
        Log "CRASH detected. Waiting 15 seconds before restart (attempt $($attempt+1))..."
        Log "Checkpoints are saved — training will continue from last epoch if resumed."
        Start-Sleep -Seconds 15
    } else {
        Log "All $($MAX_RESTARTS + 1) attempts exhausted. Check log for errors."
    }
}

# ── Done ─────────────────────────────────────────────────────────────────────
Log ""
Log "=================================================="
Log "Overnight training session ended: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Log "Exit code: $exitCode"
Log "Best checkpoint:  $ROOT\checkpoints\component_detector_v1\best.pt"
Log "Full log:         $LOG_FILE"
Log "Training report:  $ROOT\checkpoints\reports\"
Log "=================================================="

"DONE | Ended: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | Exit: $exitCode" | Set-Content $PROG_FILE

# Keep window open so you can read results in the morning
Write-Host ""
Write-Host "Press Enter to close this window..."
Read-Host

