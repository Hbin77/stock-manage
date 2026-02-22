#!/bin/sh
set -e

# DB가 없으면 최초 초기화 실행 (scheduler 서비스 전용)
if [ ! -f /app/data/stock_manage.db ]; then
    echo "[entrypoint] 최초 실행: 데이터베이스 초기화 중..."
    python main.py init
    echo "[entrypoint] 초기화 완료"
fi

exec "$@"
