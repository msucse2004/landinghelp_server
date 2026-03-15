@echo off
REM 시스템 환경변수(DEEPL_AUTH_KEY)를 물려받아 서버 실행.
REM 사용법: 환경변수 설정 후 [새로 연 CMD]에서 이 배치 실행, 또는 더블클릭(재로그인 후 권장).
REM Cursor/IDE 안에서 runserver 하면 환경변수가 안 넘어갈 수 있음.

cd /d "%~dp0"
python manage.py runserver
pause
