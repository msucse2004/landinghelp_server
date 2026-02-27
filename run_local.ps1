# venv 기반 로컬 실행 스크립트 (Windows PowerShell)
# DB는 docker compose로 db 서비스만 띄운 후 사용: docker compose up -d db

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "오류: venv가 없습니다. 먼저 .\setup_venv.ps1 를 실행하세요." -ForegroundColor Red
    exit 1
}

# DB_HOST: Docker db 서비스 사용 시 localhost (포트 5432 매핑됨)
$env:DB_HOST = "localhost"

# venv 활성화 및 실행 (dot-source로 현재 스코프에 적용)
. .\venv\Scripts\Activate.ps1

$pythonPath = (Get-Command python).Source
if ($pythonPath -notmatch "venv") {
    Write-Host "경고: venv가 활성화되지 않은 것 같습니다. python 경로: $pythonPath" -ForegroundColor Yellow
} else {
    Write-Host "venv 사용 중: $pythonPath" -ForegroundColor Green
}

python manage.py runserver 0.0.0.0:8000
