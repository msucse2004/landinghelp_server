# 이메일 환경변수 등록 스크립트 (Windows)
# 사용자 수준 환경변수로 등록 (시스템 재시작 후에도 유지)
# 실행: .\set_email_env.ps1

$ErrorActionPreference = "Stop"

Write-Host "이메일 환경변수 등록 (EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL)" -ForegroundColor Cyan
Write-Host ""

$user = Read-Host "EMAIL_HOST_USER (예: your@naver.com)"
$pass = Read-Host "EMAIL_HOST_PASSWORD" -AsSecureString
$plainPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass))
$from = Read-Host "DEFAULT_FROM_EMAIL (예: your@naver.com, 비우면 EMAIL_HOST_USER와 동일)"

if ([string]::IsNullOrWhiteSpace($from)) {
    $from = $user
}

[Environment]::SetEnvironmentVariable("EMAIL_HOST_USER", $user, "User")
[Environment]::SetEnvironmentVariable("EMAIL_HOST_PASSWORD", $plainPass, "User")
[Environment]::SetEnvironmentVariable("DEFAULT_FROM_EMAIL", $from, "User")

$plainPass = ""
Write-Host ""
Write-Host "등록 완료. 새 터미널을 열거나 현재 터미널을 재시작하면 적용됩니다." -ForegroundColor Green
