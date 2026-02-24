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
BATCH_SIZE = 100       # 배치당 종목 수 (yfinance는 100개까지 한번에 처리 가능)
BATCH_DELAY_SEC = 1.5  # 배치 간 지연 (초)
NEWS_TARGET_LIMIT = 100  # 뉴스 수집 대상 종목 수 제한 (상위 N개 + 보유 종목)


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

    MAX_CACHE_SIZE = 200  # 캐시 최대 크기 (메모리 누수 방지)

    def _get_ticker(self, symbol: str) -> yf.Ticker:
        """yfinance Ticker 객체 반환 (캐시 활용, 최대 200개 제한)"""
        if symbol not in self._cache:
            if len(self._cache) >= self.MAX_CACHE_SIZE:
                self._cache.clear()
                logger.debug(f"[캐시] Ticker 캐시 초과({self.MAX_CACHE_SIZE}개) → 초기화")
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

            # Short Interest 데이터
            stock.short_ratio = info.get("shortRatio")
            stock.short_pct_of_float = info.get("shortPercentOfFloat")
            stock.float_shares = info.get("floatShares")

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

            # Bulk upsert: N+1 쿼리 문제를 해결하기 위해 sqlite INSERT ... ON CONFLICT 사용
            rows_to_save = []
            for ts, row in df.iterrows():
                o, h, l, c, v = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), int(row["Volume"])

                # OHLCV 유효성 검증
                if c <= 0:
                    logger.warning(f"[{ticker}] 유효하지 않은 종가(close={c}) 스킵: {ts}")
                    continue
                if v < 0:
                    logger.warning(f"[{ticker}] 유효하지 않은 거래량(volume={v}) 스킵: {ts}")
                    continue
                if h < l:
                    logger.warning(f"[{ticker}] 고가({h}) < 저가({l}) 스킵: {ts}")
                    continue
                if h < c or h < o:
                    logger.warning(f"[{ticker}] 고가({h}) < 종가({c}) 또는 시가({o}) 스킵: {ts}")
                    continue
                if l > c or l > o:
                    logger.warning(f"[{ticker}] 저가({l}) > 종가({c}) 또는 시가({o}) 스킵: {ts}")
                    continue

                rows_to_save.append({
                    "stock_id": stock.id,
                    "timestamp": ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    "interval": interval,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "adj_close": c,
                })

            for row_data in rows_to_save:
                stmt = db.query(PriceHistory).filter(
                    PriceHistory.stock_id == row_data["stock_id"],
                    PriceHistory.timestamp == row_data["timestamp"],
                    PriceHistory.interval == row_data["interval"]
                ).first()
                if stmt:
                    stmt.open = row_data["open"]
                    stmt.high = row_data["high"]
                    stmt.low = row_data["low"]
                    stmt.close = row_data["close"]
                    stmt.adj_close = row_data["adj_close"]
                    stmt.volume = row_data["volume"]
                else:
                    new_record = PriceHistory(**row_data)
                    db.add(new_record)
            db.commit()

        logger.info(f"[{ticker}] {len(rows_to_save)}개 가격 데이터 저장 완료")
        return len(rows_to_save)

    @staticmethod
    def _get_realtime_volume(fi) -> int:
        """당일 실제 거래량 반환. last_volume 우선, fallback으로 three_month_average_volume."""
        try:
            volume = fi.last_volume or fi.three_month_average_volume or 0
        except Exception:
            volume = 0
        return int(volume)

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
                "volume": self._get_realtime_volume(fi),
                "market_cap": getattr(fi, "market_cap", None),
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
            }

        except Exception as e:
            logger.error(f"[{ticker}] 실시간 가격 조회 실패: {e}")
            return None

    def fetch_all_realtime_prices(self) -> dict[str, dict]:
        """
        watchlist 전체 종목의 현재가를 조회합니다.
        배치 처리 + 진행률 로그로 대규모 종목 처리에 최적화되어 있습니다.
        반환값: {ticker: price_dict}
        """
        results: dict[str, dict] = {}
        tickers = settings.WATCHLIST_TICKERS
        total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"[가격 수집] {len(tickers)}개 종목 실시간 가격 수집 시작 (배치크기={BATCH_SIZE})")

        for batch_start in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1

            for ticker in batch:
                data = self.fetch_realtime_price(ticker)
                if data:
                    results[ticker] = data

            logger.info(
                f"[가격 수집] 배치 {batch_num}/{total_batches} 완료 "
                f"({len(results)}/{len(tickers)})"
            )

            if batch_start + BATCH_SIZE < len(tickers):
                time.sleep(BATCH_DELAY_SEC)

        logger.info(f"[가격 수집] 완료: {len(results)}/{len(tickers)}개 종목 수집 성공")
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
        # VADER 감성 분석기 초기화 (루프 밖, 재사용)
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _sia = SentimentIntensityAnalyzer()
        except ImportError:
            _sia = None
            logger.warning("[뉴스] vaderSentiment 미설치 — 감성 점수 수집 불가")

        try:
            t = self._get_ticker(ticker)
            news_list = t.news  # 최대 10개 뉴스 반환

            if not news_list:
                return 0

            saved = 0
            for item in news_list:
                # 중복 체크 (URL 기준)
                url = item.get("link") or item.get("url")
                if not url:
                    logger.debug(f"[{ticker}] URL 없는 뉴스 스킵: {item.get('title', 'N/A')[:50]}")
                    continue
                existing = db.query(MarketNews).filter(MarketNews.url == url).first()
                if existing:
                    continue

                published_ts = item.get("providerPublishTime")
                published_dt = (
                    datetime.fromtimestamp(published_ts, tz=timezone.utc).replace(tzinfo=None)
                    if published_ts
                    else None
                )

                # VADER 감성 점수 계산 (title + summary 합산)
                # NOTE: VADER는 금융 도메인 특화가 아님. AI 분석 시 뉴스 제목 원문을 직접 참조하여 보완됨
                sentiment_score = None
                if _sia:
                    text = item.get("title", "")
                    if item.get("summary"):
                        text += " " + item["summary"]
                    scores = _sia.polarity_scores(text)
                    sentiment_score = round(scores["compound"], 4)

                news = MarketNews(
                    ticker=ticker,
                    title=item.get("title", "")[:500],
                    summary=item.get("summary"),
                    url=url,
                    source=item.get("publisher"),
                    published_at=published_dt,
                    sentiment=sentiment_score,
                )
                db.add(news)
                saved += 1

            logger.debug(f"[{ticker}] 뉴스 {saved}건 저장")
            return saved

        except Exception as e:
            logger.error(f"[{ticker}] 뉴스 수집 실패: {e}")
            return 0

    def _get_news_target_tickers(self) -> list[str]:
        """
        뉴스 수집 대상 종목을 선정합니다.
        800개 전체 수집은 비효율적이므로, 보유 종목 + AI 분석 우선순위 상위 종목으로 제한합니다.

        우선순위:
          1. 포트폴리오 보유 종목 (전체)
          2. 최근 AI 추천 종목
          3. 나머지 watchlist에서 NEWS_TARGET_LIMIT까지 채움
        """
        all_tickers = settings.WATCHLIST_TICKERS

        # 종목 수가 NEWS_TARGET_LIMIT 이하면 전체 수집
        if len(all_tickers) <= NEWS_TARGET_LIMIT:
            return all_tickers

        target_set: set[str] = set()

        # 1) 보유 종목 추가
        try:
            from database.connection import SessionLocal
            from database.models import PortfolioHolding, Stock as StockModel
            db = SessionLocal()
            try:
                rows = (
                    db.query(StockModel.ticker)
                    .join(PortfolioHolding, PortfolioHolding.stock_id == StockModel.id)
                    .filter(PortfolioHolding.quantity > 0)
                    .all()
                )
                target_set.update(r.ticker for r in rows)
            finally:
                db.close()
        except Exception:
            pass

        # 2) 최근 AI 추천 종목 추가
        try:
            from database.models import AIRecommendation, Stock
            from database.connection import SessionLocal
            db = SessionLocal()
            try:
                from datetime import timedelta
                cutoff = datetime.now() - timedelta(days=7)
                recs = (
                    db.query(Stock.ticker)
                    .join(AIRecommendation, AIRecommendation.stock_id == Stock.id)
                    .filter(AIRecommendation.created_at >= cutoff)
                    .distinct()
                    .all()
                )
                target_set.update(r.ticker for r in recs)
            finally:
                db.close()
        except Exception:
            pass

        # 3) 나머지를 watchlist 순서대로 채움
        for ticker in all_tickers:
            if len(target_set) >= NEWS_TARGET_LIMIT:
                break
            target_set.add(ticker)

        result = [t for t in all_tickers if t in target_set]
        logger.info(f"[뉴스] 수집 대상: {len(result)}개 (보유+AI추천 우선, 전체 {len(all_tickers)}개 중)")
        return result

    def fetch_all_news(self) -> int:
        """
        뉴스 수집 대상 종목의 뉴스를 수집하고 총 저장 건수를 반환합니다.
        대규모 종목(800+)에서는 보유 종목 + AI 추천 상위 종목으로 제한하여 효율성을 높입니다.
        """
        total = 0
        tickers = self._get_news_target_tickers()
        total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"전체 뉴스 수집 시작 ({len(tickers)}개 종목, 배치크기={BATCH_SIZE})...")

        for batch_start in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
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
