"""
DeepL API 키 조회: 시스템 환경변수만 사용 (보안).
1) os.environ (프로세스가 물려받은 값)
2) Windows 레지스트리 (사용자/시스템 환경변수)
3) PowerShell로 동일 사용자 환경변수 조회

서버가 키를 못 읽을 때: Cursor/IDE 내부 터미널은 부모 프로세스 환경만 물려받아
시스템에 등록한 변수가 없을 수 있음. 해결: Windows에서 [새 CMD/PowerShell]을 연 뒤
프로젝트 폴더에서 runserver.bat 또는 python manage.py runserver 실행.
"""
import os
import subprocess


def _read_key_from_registry_winreg():
    """winreg로 레지스트리에서 DEEPL_AUTH_KEY 읽기."""
    try:
        import winreg
        for access in [winreg.KEY_READ, getattr(winreg, 'KEY_WOW64_64KEY', 0x100) | winreg.KEY_READ]:
            for root, key_name in [
                (winreg.HKEY_CURRENT_USER, r'Environment'),
                (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
            ]:
                try:
                    with winreg.OpenKey(root, key_name, 0, access) as reg_key:
                        val, _ = winreg.QueryValueEx(reg_key, 'DEEPL_AUTH_KEY')
                        key = (val or '').strip()
                        if isinstance(key, bytes):
                            key = key.decode('utf-8', errors='ignore').strip()
                        if key:
                            return key
                except (FileNotFoundError, OSError, TypeError):
                    continue
    except Exception:
        pass
    return ''


def _read_key_via_powershell():
    """PowerShell로 사용자/시스템 환경변수에서 DEEPL_AUTH_KEY 읽기 (동일 사용자 레지스트리)."""
    if os.name != 'nt':
        return ''
    script = (
        "$u = [Environment]::GetEnvironmentVariable('DEEPL_AUTH_KEY', 'User'); "
        "$m = [Environment]::GetEnvironmentVariable('DEEPL_AUTH_KEY', 'Machine'); "
        "if ($u) { $u.Trim() } elseif ($m) { $m.Trim() } else { '' }"
    )
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        key = (out.stdout or '').strip()
        return key if key else ''
    except Exception:
        return ''


def get_deepl_auth_key():
    """
    시스템 환경변수만 사용 (보안). 순서: os.environ → Windows 레지스트리 → PowerShell.
    .env 파일은 사용하지 않음. 서버는 '시스템 환경변수를 물려받는 방식'으로 실행해야 함.
    """
    key = (os.environ.get('DEEPL_AUTH_KEY') or '').strip()
    if key:
        return key
    if os.name == 'nt':
        key = _read_key_from_registry_winreg()
        if key:
            return key
        key = _read_key_via_powershell()
        if key:
            return key
    return ''

