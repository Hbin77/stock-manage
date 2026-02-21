"""
실시간 시장 데이터 수집 모듈
yfinance를 사용하여 주가 데이터, 종목 정보, 뉴스를 수집하고
데이터베이스에 저장합니다.
"""
from datetime import datetime, timedelta, timezone
import time
from typing import Optional

import pandas as pd
import yfinance as yf
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config.settings import settings
from database.connection import get_db
from database.models import MarketNews, PriceHistory, Stock

# 대규모 종목 처리 시 rate limit 방지용 배치 설정
BATCH_SIZE = 50        # 배치당 종목 수
BATCH_DELAY_SEC = 2.0  # 배치 간 지연 (초)


class MarketDataFetcher:
    """
    yfinance 기반 시장 데이터 수집기

    주요 기능:
      - 종목 메타 정보 동기화 (회사명, 섹터, 시가총액 등)
      - OHLCV 일봉 / 분봉 데이터 수집 및 저장
      - 실시간 현재가 조회
      - 뉴스 수집
    """

    def __init__(self):
        self._cache: dict[str, yf.Ticker] = {}  # Ticker 객체 캐시

    def _get_ticker(self, symbol: str) -> yf.Ticker:
        """yfinance Ticker 객체 반환 (캐시 활용)"""
        if symbol not in self._cache:
            self._cache[symbol] = yf.Ticker(symbol)
        return self._cache[symbol]

    # ─────────────────────────────────────────
    # 종목 메타 정보
    # ─────────────────────────────────────────
    def sync_stock_info(self, ticker: str, db: Session) -> Optional[Stock]:
        """
        종목 기본 정보를 DB에 저장/업데이트합니다.
        신규 종목이면 INSERT, 기존 종목이면 UPDATE합니다.

        yfinance 1.x에서 .info 대신 .fast_info + .get_info()를 사용하며
        실패 시 ticker 이름만으로 최소 등록을 허용합니다.
        """
        try:
            t = self._get_ticker(ticker)

            # fast_info: 현재가/시가총액 등 가볍게 조회 가능
            fi = t.fast_info

            # 현재가 확인으로 유효 종목 검증
            current_price = getattr(fi, "last_price", None)
            if current_price is None:
                logger.warning(f"[{ticker}] 유효한 종목 정보 없음 (fast_info 실패), 건너뜀")
                return None

            # .info 는 rate-limit 에 걸릴 수 있어 별도 try
            info: dict = {}
            try:
                info = t.info or {}
            except Exception:
                pass  # info 실패 시 fast_info 값만 사용

            name = (
                info.get("longName")
                or info.get("shortName")
                or getattr(fi, "exchange", None)
                or ticker
            )

            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                stock = Stock(ticker=ticker, name=name)
                db.add(stock)
                logger.info(f"[{ticker}] 신규 종목 등록: {name}")
            else:
                stock.name = name

            stock.sector = info.get("sector")
            stock.industry = info.get("industry")
            stock.market_cap = info.get("marketCap") or getattr(fi, "market_cap", None)
            stock.currency = info.get("currency") or getattr(fi, "currency", "USD")
            stock.exchange = info.get("exchange") or getattr(fi, "exchange", None)
            stock.country = info.get("country")
            stock.is_active = True

            db.flush()
            logger.debug(f"[{ticker}] 종목 정보 동기화 완료 (현재가: {current_price})")
            return stock

        except Exception as e:
            logger.error(f"[{ticker}] 종목 정보 수집 실패: {e}")
            return None

    def sync_all_watchlist(self) -> dict[str, bool]:
        """
        watchlist의 모든 종목 메타 정보를 동기화합니다.
        50개씩 배치 처리하여 rate limit을 방지합니다.
        반환값: {ticker: 성공여부}
        """
        results: dict[str, bool] = {}
        tickers = settings.WATCHLIST_TICKERS
        logger.info(f"관심 종목 {len(tickers)}개 동기화 시작 (배치크기={BATCH_SIZE})...")

        for batch_start in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"배치 {batch_num}/{total_batches} 처리 중 ({len(batch)}개 종목)...")

            with get_db() as db:
                for ticker in batch:
                    stock = self.sync_stock_info(ticker, db)
                    results[ticker] = stock is not None

            if batch_start + BATCH_SIZE < len(tickers):
                logger.debug(f"배치 완료, {BATCH_DELAY_SEC}초 대기...")
                time.sleep(BATCH_DELAY_SEC)

        success = sum(results.values())
        logger.info(f"관심 종목 동기화 완료: {success}/{len(results)} 성공")
        return results

    # ─────────────────────────────────────────
    # OHLCV 가격 데이터 수집
    # ─────────────────────────────────────────
    def fetch_price_history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        종목의 가격 이력을 DataFrame으로 반환합니다.

        Args:
            ticker  : 종목 코드 (예: AAPL, 005930.KS)
            period  : 조회 기간 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max)
            interval: 봉 단위 (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo)
        """
        try:
            t = self._get_ticker(ticker)
            df = t.history(period=period, interval=interval, auto_adjust=True)

            if df.empty:
                logger.warning(f"[{ticker}] 가격 데이터 없음 (period={period}, interval={interval})")
                return pd.DataFrame()

            df.index = pd.to_datetime(df.index)
            # timezone-aware → UTC naive 변환 (SQLite 호환성)
            if df.index.tzinfo is not None:
                df.index = df.index.tz_convert("UTC").tz_localize(None)

            logger.debug(f"[{ticker}] {len(df)}개 캔들 수집 완료 (interval={interval})")
            return df

        except Exception as e:
            logger.error(f"[{ticker}] 가격 이력 수집 실패: {e}")
            return pd.DataFrame()

    def save_price_history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> int:
        """
        가격 이력을 DB에 저장하고 저장된 행 수를 반환합니다.
        중복 데이터는 무시(INSERT OR IGNORE)합니다.
        """
        df = self.fetch_price_history(ticker, period=period, interval=interval)
        if df.empty:
            return 0

        with get_db() as db:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                stock = self.sync_stock_info(ticker, db)
            if stock is None:
                return 0

            saved = 0
            for ts, row in df.iterrows():
                # 이미 존재하는 레코드는 건너뜀 (UNIQUE 제약 활용)
                existing = (
                    db.query(PriceHistory)
                    .filter(
                        PriceHistory.stock_id == stock.id,
                        PriceHistory.timestamp == ts,
                        PriceHistory.interval == interval,
                    )
                    .first()
                )
                if existing:
                    continue

                ph = PriceHistory(
                    stock_id=stock.id,
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    interval=interval,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                    adj_close=float(row.get("Close", row["Close"])),
                )
                db.add(ph)
                saved += 1

        logger.info(f"[{ticker}] {saved}개 가격 데이터 저장 완료")
        return saved

    def fetch_realtime_price(self, ticker: str) -> Optional[dict]:
        """
        단일 종목의 현재가 정보를 실시간으로 조회합니다.
        fast_info 우선, history fallback 방식으로 안정적으로 조회합니다.

        반환 예시:
            {
                "ticker": "AAPL",
                "price": 195.89,
                "change": 2.34,
                "change_pct": 1.21,
                "volume": 45_230_000,
                "market_cap": 3_010_000_000_000,
                "timestamp": datetime(...)
            }
        """
        try:
            t = self._get_ticker(ticker)
            fi = t.fast_info

            price = getattr(fi, "last_price", None)

            # fast_info 실패 시 최근 history로 fallback
            if price is None:
                hist = t.history(period="1d", interval="1m")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])

            if price is None:
                logger.warning(f"[{ticker}] 현재가 조회 실패")
                return None

            prev_close = getattr(fi, "previous_close", None) or price
            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0.0

            return {
                "ticker": ticker,
                "price": float(price),
                "change": float(change),
                "change_pct": float(change_pct),
                "volume": getattr(fi, "three_month_average_volume", 0) or 0,
                "market_cap": getattr(fi, "market_cap", None),
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
            }

        except Exception as e:
            logger.error(f"[{ticker}] 실시간 가격 조회 실패: {e}")
            return None

    def fetch_all_realtime_prices(self) -> dict[str, dict]:
        """
        watchlist 전체 종목의 현재가를 조회합니다.
        반환값: {ticker: price_dict}
        """
        results: dict[str, dict] = {}
        for ticker in settings.WATCHLIST_TICKERS:
            data = self.fetch_realtime_price(ticker)
            if data:
                results[ticker] = data
                logger.debug(
                    f"[{ticker}] 현재가: ${data['price']:.2f} "
                    f"({data['change_pct']:+.2f}%)"
                )
        return results

    # ─────────────────────────────────────────
    # 최신 일봉 업데이트 (장 마감 후 실행)
    # ─────────────────────────────────────────
    def update_daily_prices(self) -> dict[str, int]:
        """
        모든 watchlist 종목의 최근 5일 일봉 데이터를 업데이트합니다.
        50개씩 배치 처리하여 rate limit을 방지합니다.
        매일 장 마감 후 실행을 권장합니다.
        """
        results: dict[str, int] = {}
        tickers = settings.WATCHLIST_TICKERS
        logger.info(f"일봉 데이터 업데이트 시작 ({len(tickers)}개 종목, 배치크기={BATCH_SIZE})...")

        for batch_start in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"배치 {batch_num}/{total_batches} 처리 중...")

            for ticker in batch:
                saved = self.save_price_history(ticker, period="5d", interval="1d")
                results[ticker] = saved

            if batch_start + BATCH_SIZE < len(tickers):
                time.sleep(BATCH_DELAY_SEC)

        total = sum(results.values())
        logger.success(f"일봉 업데이트 완료: 총 {total}개 레코드 저장")
        return results

    # ─────────────────────────────────────────
    # 뉴스 수집
    # ─────────────────────────────────────────
    def fetch_and_save_news(self, ticker: str, db: Session) -> int:
        """
        종목 관련 최신 뉴스를 수집하여 DB에 저장합니다.
        반환값: 저장된 뉴스 수
        """
        try:
            t = self._get_ticker(ticker)
            news_list = t.news  # 최대 10개 뉴스 반환

            if not news_list:
                return 0

            saved = 0
            for item in news_list:
                # 중복 체크 (URL 기준)
                url = item.get("link") or item.get("url")
                if url:
                    existing = db.query(MarketNews).filter(MarketNews.url == url).first()
                    if existing:
                        continue

                published_ts = item.get("providerPublishTime")
                published_dt = (
                    datetime.fromtimestamp(published_ts, tz=timezone.utc).replace(tzinfo=None)
                    if published_ts
                    else None
                )

                news = MarketNews(
                    ticker=ticker,
                    title=item.get("title", "")[:500],
                    summary=item.get("summary"),
                    url=url,
                    source=item.get("publisher"),
                    published_at=published_dt,
                )
                db.add(news)
                saved += 1

            logger.debug(f"[{ticker}] 뉴스 {saved}건 저장")
            return saved

        except Exception as e:
            logger.error(f"[{ticker}] 뉴스 수집 실패: {e}")
            return 0

    def fetch_all_news(self) -> int:
        """
        watchlist 전체 종목의 뉴스를 수집하고 총 저장 건수를 반환합니다.
        50개씩 배치 처리하여 rate limit을 방지합니다.
        """
        total = 0
        tickers = settings.WATCHLIST_TICKERS
        logger.info(f"전체 뉴스 수집 시작 ({len(tickers)}개 종목, 배치크기={BATCH_SIZE})...")

        for batch_start in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"뉴스 배치 {batch_num}/{total_batches} 처리 중...")

            with get_db() as db:
                for ticker in batch:
                    total += self.fetch_and_save_news(ticker, db)

            if batch_start + BATCH_SIZE < len(tickers):
                time.sleep(BATCH_DELAY_SEC)

        logger.info(f"전체 뉴스 수집 완료: {total}건 저장")
        return total

    # ─────────────────────────────────────────
    # 초기 데이터 로드 (최초 실행 시)
    # ─────────────────────────────────────────
    def initial_load(self, years: int = 2) -> None:
        """
        최초 실행 시 watchlist 전체의 과거 데이터를 로드합니다.

        Args:
            years: 로드할 과거 데이터 연수 (기본 2년)
        """
        period_map = {1: "1y", 2: "2y", 5: "5y"}
        period = period_map.get(years, "2y")

        logger.info(f"초기 데이터 로드 시작 (기간: {period}년)...")

        # 1단계: 종목 메타 정보 동기화
        self.sync_all_watchlist()

        # 2단계: 일봉 가격 이력 수집 (배치 처리)
        tickers = settings.WATCHLIST_TICKERS
        total_records = 0
        for batch_start in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[batch_start:batch_start + BATCH_SIZE]
            for ticker in batch:
                saved = self.save_price_history(ticker, period=period, interval="1d")
                total_records += saved
            if batch_start + BATCH_SIZE < len(tickers):
                time.sleep(BATCH_DELAY_SEC)

        # 3단계: 뉴스 수집
        news_count = self.fetch_all_news()

        logger.success(
            f"초기 데이터 로드 완료 - "
            f"가격 레코드: {total_records}개, 뉴스: {news_count}건"
        )


# 싱글톤 인스턴스
market_fetcher = MarketDataFetcher()
