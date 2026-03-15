# venv 생성 및 의존성 설치 (Windows PowerShell)
# 사용: .\setup_venv.ps1

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not (Test-Path "venv")) {
    Write-Host "venv 생성 중..."
    python -m venv venv
}
Write-Host "venv 활성화 및 의존성 설치..."
. .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Write-Host "완료. 실행: .\run_local.ps1"
