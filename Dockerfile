FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 설치 (소스 변경 시 캐시 재활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사 (.dockerignore로 .env, *.db 등 제외됨)
COPY . .

# 런타임 디렉토리 생성 (볼륨 마운트 전 기본 폴더)
RUN mkdir -p /app/data /app/logs

# 엔트리포인트 실행 권한
RUN chmod +x /app/docker-entrypoint.sh
