FROM python:3.12-slim

# Docker 모범 사례 — 불필요한 .pyc 파일 생성 방지, 로그 버퍼링 비활성화
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 타임존 패키지 설치 (NAS 환경 TZ 설정 지원)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

# 의존성 먼저 설치 (소스 변경 시 캐시 재활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사 (.dockerignore로 .env, *.db 등 제외됨)
COPY . .

# 런타임 디렉토리 생성 (볼륨 마운트 전 기본 폴더)
RUN mkdir -p /app/data /app/logs

# 엔트리포인트 실행 권한
RUN chmod +x /app/docker-entrypoint.sh

# 기본 실행 명령 (docker-compose에서 command로 오버라이드됨)
CMD ["python", "main.py", "run"]
