#!/bin/bash
# venv 기반 로컬 실행 스크립트 (Unix / Mac / Linux)
# DB는 docker compose로 db 서비스만 띄운 후 사용: docker compose up -d db

set -e
cd "$(dirname "$0")"

if [ ! -f "venv/bin/activate" ]; then
    echo "오류: venv가 없습니다. 먼저 ./setup_venv.sh 를 실행하세요."
    exit 1
fi

export DB_HOST=localhost

# venv 활성화 및 실행
source venv/bin/activate

if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "경고: VIRTUAL_ENV가 설정되지 않았습니다. venv가 활성화되지 않은 것 같습니다."
else
    echo "venv 사용 중: $VIRTUAL_ENV"
fi

python manage.py runserver 0.0.0.0:8000
