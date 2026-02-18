#!/bin/bash
# venv 기반 로컬 실행 스크립트 (Unix / Mac / Linux)
# DB는 docker compose로 db 서비스만 띄운 후 사용: docker compose up -d db

set -e
cd "$(dirname "$0")"

export DB_HOST=localhost

# venv 활성화 및 실행
source venv/bin/activate
python manage.py runserver 0.0.0.0:8000
