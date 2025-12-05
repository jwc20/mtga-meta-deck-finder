$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$VenvPaths = @("venv\Scripts\Activate.ps1", ".venv\Scripts\Activate.ps1")
$VenvActivated = $false

foreach ($VenvPath in $VenvPaths) {
    if (Test-Path $VenvPath) {
        & $VenvPath
        $VenvActivated = $true
        break
    }
}

if (-not $VenvActivated) {
    Write-Host "No virtual environment found. Creating .venv..."
    python -m venv .venv
    & ".venv\Scripts\Activate.ps1"
    Write-Host "Installing dependencies..."
    pip install --upgrade pip
    if (Test-Path "pyproject.toml") {
        pip install -e .
    } elseif (Test-Path "requirements.txt") {
        pip install -r requirements.txt
    }
    Write-Host "Virtual environment created and activated."
}

$FollowerProcess = $null
$FastAPIProcess = $null

function Cleanup {
    Write-Host ""
    Write-Host "Shutting down gracefully..."
    
    if ($FastAPIProcess -and !$FastAPIProcess.HasExited) {
        Write-Host "Stopping FastAPI app (PID: $($FastAPIProcess.Id))..."
        Stop-Process -Id $FastAPIProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "FastAPI app stopped."
    }
    
    if ($FollowerProcess -and !$FollowerProcess.HasExited) {
        Write-Host "Stopping MTGA Follower (PID: $($FollowerProcess.Id))..."
        Stop-Process -Id $FollowerProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "MTGA Follower stopped."
    }
    
    Write-Host "All processes stopped."
}

try {
    Write-Host "Starting MTGA Follower..."
    $FollowerProcess = Start-Process -FilePath "python" -ArgumentList "seventeenlands/mtga_follower.py" -PassThru -NoNewWindow
    Write-Host "MTGA Follower started (PID: $($FollowerProcess.Id))"

    Write-Host "Starting FastAPI app..."
    $FastAPIProcess = Start-Process -FilePath "uvicorn" -ArgumentList "app.main:app", "--reload", "--host=0.0.0.0", "--port=8765" -PassThru -NoNewWindow
    Write-Host "FastAPI app started (PID: $($FastAPIProcess.Id))"

    Write-Host ""
    Write-Host "Both processes running. Press Ctrl+C to stop."
    Write-Host ""

    while ($true) {
        if ($FollowerProcess.HasExited -and $FastAPIProcess.HasExited) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    Cleanup
}
