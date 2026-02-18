#!/bin/bash
# venv 생성 및 의존성 설치 (Bash - Git Bash, WSL, Mac, Linux)
# 사용: ./setup_venv.sh

set -e
cd "$(dirname "$0")"

if [[ ! -d venv ]]; then
    echo "venv 생성 중..."
    python -m venv venv
fi
echo "venv 활성화 및 의존성 설치..."
source venv/bin/activate
pip install -r requirements.txt
echo "완료. 실행: ./run_local.sh"
