"""
시스템 전역 설정 모듈
.env 파일에서 환경 변수를 읽어 애플리케이션 전체에 제공합니다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 디렉토리
BASE_DIR = Path(__file__).resolve().parent.parent

# .env 파일 로드
load_dotenv(BASE_DIR / ".env")


class Settings:
    # --- 프로젝트 경로 ---
    BASE_DIR: Path = BASE_DIR
    LOG_DIR: Path = BASE_DIR / "logs"

    # --- AI (Google Gemini) ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    AI_MAX_TOKENS: int = int(os.getenv("AI_MAX_TOKENS", "2048"))
    AI_TEMPERATURE: float = float(os.getenv("AI_TEMPERATURE", "0.3"))
    BUY_CONFIDENCE_THRESHOLD: float = float(os.getenv("BUY_CONFIDENCE_THRESHOLD", "0.65"))
    SELL_CONFIDENCE_THRESHOLD: float = float(os.getenv("SELL_CONFIDENCE_THRESHOLD", "0.60"))

    # --- 카카오톡 알림 ---
    KAKAO_REST_API_KEY: str = os.getenv("KAKAO_REST_API_KEY", "")
    KAKAO_ACCESS_TOKEN: str = os.getenv("KAKAO_ACCESS_TOKEN", "")
    KAKAO_REFRESH_TOKEN: str = os.getenv("KAKAO_REFRESH_TOKEN", "")

    # --- 텔레그램 알림 ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- 데이터베이스 ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR}/stock_manage.db"
    )

    # --- 모니터링 종목 ---
    # 포트폴리오 보유 종목을 우선 사용 (DB 조회)
    # DB가 없거나 보유 종목이 없을 경우 WATCHLIST_TICKERS 환경변수로 폴백
    @property
    def WATCHLIST_TICKERS(self) -> list[str]:
        try:
            from database.connection import SessionLocal
            from database.models import PortfolioHolding, Stock
            db = SessionLocal()
            try:
                rows = (
                    db.query(Stock.ticker)
                    .join(PortfolioHolding, PortfolioHolding.stock_id == Stock.id)
                    .filter(PortfolioHolding.quantity > 0)
                    .all()
                )
                if rows:
                    return [r.ticker for r in rows]
            finally:
                db.close()
        except Exception:
            pass

        # 폴백: 환경변수 (최초 init 시 또는 포트폴리오가 비어있을 때)
        raw = os.getenv("WATCHLIST_TICKERS", "")
        if raw.strip():
            return [t.strip() for t in raw.split(",") if t.strip()]

        return []

    # --- 스케줄 설정 ---
    FETCH_INTERVAL_MINUTES: int = int(os.getenv("FETCH_INTERVAL_MINUTES", "5"))
    DAILY_ANALYSIS_TIME: str = os.getenv("DAILY_ANALYSIS_TIME", "09:00")

    # --- 로깅 ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", str(LOG_DIR / "stock_manage.log"))

    # --- Slack 알림 (레거시) ---
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")

    # --- 기술적 분석 파라미터 ---
    # RSI 과매도/과매수 기준
    RSI_OVERSOLD: int = 30
    RSI_OVERBOUGHT: int = 70

    # 볼린저 밴드 기간
    BOLLINGER_PERIOD: int = 20
    BOLLINGER_STD: float = 2.0

    # 이동평균선 기간
    MA_SHORT: int = 20
    MA_LONG: int = 50
    MA_SIGNAL: int = 9  # MACD 시그널


settings = Settings()

# logs 디렉토리 자동 생성
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
