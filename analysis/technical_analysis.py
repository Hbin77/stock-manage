"""
기술적 지표 계산 모듈
pandas와 ta 라이브러리를 사용하여 주요 기술적 지표를 계산하고
TechnicalIndicator 테이블에 저장합니다.

지원 지표:
  - RSI (상대강도지수, 14일)
  - MACD (이동평균수렴발산)
  - 볼린저 밴드 (20일, 2σ)
  - 이동평균선 (MA20, MA50, MA200)
  - 거래량 이동평균 (VMA20)
"""
from datetime import datetime

import pandas as pd
from loguru import logger

try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logger.warning("ta 라이브러리가 설치되지 않았습니다. pip install ta 로 설치하세요.")

from config.settings import settings
from database.connection import get_db
from database.models import PriceHistory, Stock, TechnicalIndicator


class TechnicalAnalyzer:
    """기술적 지표 계산 및 저장"""

    def _load_price_df(self, ticker: str, db, lookback_days: int = 350) -> pd.DataFrame:
        """DB에서 가격 이력을 불러와 DataFrame으로 반환합니다."""
        stock = db.query(Stock).filter(Stock.ticker == ticker).first()
        if stock is None:
            return pd.DataFrame()

        rows = (
            db.query(PriceHistory)
            .filter(
                PriceHistory.stock_id == stock.id,
                PriceHistory.interval == "1d",
            )
            .order_by(PriceHistory.timestamp.asc())
            .all()
        )

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(
            [
                {
                    "date": r.timestamp,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows[-lookback_days:]
            ]
        )
        df.set_index("date", inplace=True)
        return df

    def calculate_and_save(self, ticker: str) -> int:
        """
        종목의 기술적 지표를 계산하고 DB에 저장합니다.
        반환값: 저장된 날짜 수
        """
        if not TA_AVAILABLE:
            logger.error("ta 라이브러리가 없어 기술적 지표를 계산할 수 없습니다.")
            return 0

        with get_db() as db:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                return 0

            df = self._load_price_df(ticker, db)
            if len(df) < 30:
                logger.warning(f"[{ticker}] 데이터 부족 ({len(df)}일), 기술적 지표 계산 불가")
                return 0

            close = df["close"]
            high = df["high"]
            low = df["low"]
            volume = df["volume"]

            # ── RSI ──────────────────────────
            rsi = ta.momentum.RSIIndicator(close=close, window=14).rsi()

            # ── MACD ─────────────────────────
            macd_ind = ta.trend.MACD(
                close=close,
                window_slow=26,
                window_fast=12,
                window_sign=settings.MA_SIGNAL,
            )
            macd_line = macd_ind.macd()
            macd_signal = macd_ind.macd_signal()
            macd_hist = macd_ind.macd_diff()

            # ── 볼린저 밴드 ──────────────────
            bb = ta.volatility.BollingerBands(
                close=close,
                window=settings.BOLLINGER_PERIOD,
                window_dev=settings.BOLLINGER_STD,
            )
            bb_upper = bb.bollinger_hband()
            bb_middle = bb.bollinger_mavg()
            bb_lower = bb.bollinger_lband()

            # ── 이동평균선 ───────────────────
            ma_20 = close.rolling(window=20).mean()
            ma_50 = close.rolling(window=50).mean()
            ma_200 = close.rolling(window=200).mean()
            vol_ma_20 = volume.rolling(window=20).mean()

            # ── DB 저장 ──────────────────────
            saved = 0
            for date_idx in df.index:
                existing = (
                    db.query(TechnicalIndicator)
                    .filter(
                        TechnicalIndicator.stock_id == stock.id,
                        TechnicalIndicator.date == date_idx,
                    )
                    .first()
                )

                def _val(series, idx):
                    v = series.get(idx)
                    return None if (v is None or pd.isna(v)) else float(v)

                indicator_data = dict(
                    rsi_14=_val(rsi, date_idx),
                    macd=_val(macd_line, date_idx),
                    macd_signal=_val(macd_signal, date_idx),
                    macd_hist=_val(macd_hist, date_idx),
                    bb_upper=_val(bb_upper, date_idx),
                    bb_middle=_val(bb_middle, date_idx),
                    bb_lower=_val(bb_lower, date_idx),
                    ma_20=_val(ma_20, date_idx),
                    ma_50=_val(ma_50, date_idx),
                    ma_200=_val(ma_200, date_idx),
                    volume_ma_20=_val(vol_ma_20, date_idx),
                )

                if existing:
                    for k, v in indicator_data.items():
                        setattr(existing, k, v)
                else:
                    ind = TechnicalIndicator(
                        stock_id=stock.id,
                        date=date_idx,
                        **indicator_data,
                    )
                    db.add(ind)
                    saved += 1

            logger.debug(f"[{ticker}] 기술적 지표 계산 완료 ({saved}개 신규 저장)")
            return saved

    def calculate_all(self) -> dict[str, int]:
        """watchlist 전체 종목의 기술적 지표를 계산합니다."""
        results = {}
        for ticker in settings.WATCHLIST_TICKERS:
            results[ticker] = self.calculate_and_save(ticker)
        return results

    def get_latest_indicators(self, ticker: str) -> dict | None:
        """특정 종목의 가장 최근 기술적 지표를 반환합니다."""
        with get_db() as db:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                return None

            ind = (
                db.query(TechnicalIndicator)
                .filter(TechnicalIndicator.stock_id == stock.id)
                .order_by(TechnicalIndicator.date.desc())
                .first()
            )
            if ind is None:
                return None

            return {
                "ticker": ticker,
                "date": ind.date.strftime("%Y-%m-%d"),
                "rsi_14": ind.rsi_14,
                "macd": ind.macd,
                "macd_signal": ind.macd_signal,
                "macd_hist": ind.macd_hist,
                "bb_upper": ind.bb_upper,
                "bb_middle": ind.bb_middle,
                "bb_lower": ind.bb_lower,
                "ma_20": ind.ma_20,
                "ma_50": ind.ma_50,
                "ma_200": ind.ma_200,
                "volume_ma_20": ind.volume_ma_20,
            }


# 싱글톤 인스턴스
technical_analyzer = TechnicalAnalyzer()
