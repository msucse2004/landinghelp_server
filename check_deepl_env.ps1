# DEEPL_AUTH_KEY in Windows env (Machine / User / Process)
$machine = [Environment]::GetEnvironmentVariable('DEEPL_AUTH_KEY', 'Machine')
$user = [Environment]::GetEnvironmentVariable('DEEPL_AUTH_KEY', 'User')
$process = $env:DEEPL_AUTH_KEY

Write-Host "=== Windows DEEPL_AUTH_KEY ==="
Write-Host "Machine (시스템 전체): $(if ($machine) { '설정됨 (길이: ' + $machine.Length + ')' } else { '없음' })"
Write-Host "User (현재 사용자):   $(if ($user) { '설정됨 (길이: ' + $user.Length + ')' } else { '없음' })"
Write-Host "Process (이 터미널):   $(if ($process) { '설정됨 (길이: ' + $process.Length + ')' } else { '없음' })"
