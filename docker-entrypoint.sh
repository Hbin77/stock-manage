#!/bin/sh
set -e

if [ ! -f /app/data/stock_manage.db ]; then
    echo "[entrypoint] 최초 실행: 데이터베이스 초기화 중..."
    python main.py init
    echo "[entrypoint] 초기화 완료"
else
    echo "[entrypoint] 기존 DB 발견: 마이그레이션 체크..."
    python -c "from database.connection import init_db; init_db()"
    echo "[entrypoint] 마이그레이션 완료"
fi

exec "$@"
