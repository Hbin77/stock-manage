"""
데이터베이스 ORM 모델 정의
SQLAlchemy 2.0 스타일의 선언적 매핑을 사용합니다.

테이블 구성:
  - stocks           : 종목 기본 정보 (티커, 회사명, 섹터 등)
  - price_history    : OHLCV 가격 이력 (일봉/분봉)
  - technical_indicators : 기술적 지표 캐시 (RSI, MACD, 볼린저 등)
  - portfolio_holdings   : 현재 보유 종목
  - transactions         : 매수/매도 거래 내역
  - ai_recommendations   : AI 매수 추천 이력
  - sell_signals         : AI 매도 신호 이력
  - price_alerts         : 종목별 가격/거래량 알림 조건 설정
  - alert_history        : 실제 발화된 알림 이력 (중복 방지 및 감사 로그)
  - market_news          : 수집된 뉴스/이벤트
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """모든 모델의 공통 베이스 클래스"""
    pass


# ─────────────────────────────────────────────
# 1. 종목 기본 정보
# ─────────────────────────────────────────────
class Stock(Base):
    """
    주식 종목 기본 정보 테이블
    yfinance의 Ticker.info 에서 메타 데이터를 수집합니다.
    """
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    market_cap: Mapped[float | None] = mapped_column(Float)          # 시가총액 (USD)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    exchange: Mapped[str | None] = mapped_column(String(50))         # NASDAQ, NYSE, KRX …
    country: Mapped[str | None] = mapped_column(String(50))
    short_ratio: Mapped[float | None] = mapped_column(Float, default=None)
    short_pct_of_float: Mapped[float | None] = mapped_column(Float, default=None)
    float_shares: Mapped[float | None] = mapped_column(Float, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)   # 모니터링 활성 여부
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # 관계
    price_history: Mapped[list["PriceHistory"]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    indicators: Mapped[list["TechnicalIndicator"]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    holdings: Mapped[list["PortfolioHolding"]] = relationship(back_populates="stock")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="stock")
    recommendations: Mapped[list["AIRecommendation"]] = relationship(back_populates="stock")
    sell_signals: Mapped[list["SellSignal"]] = relationship(back_populates="stock")
    price_alerts: Mapped[list["PriceAlert"]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )
    alert_history: Mapped[list["AlertHistory"]] = relationship(
        back_populates="stock", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Stock {self.ticker} ({self.name})>"


# ─────────────────────────────────────────────
# 2. OHLCV 가격 이력
# ─────────────────────────────────────────────
class PriceHistory(Base):
    """
    종목별 OHLCV(시가/고가/저가/종가/거래량) 데이터
    interval: '1d' 일봉, '1h' 시간봉, '5m' 5분봉 등
    """
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("stock_id", "timestamp", "interval", name="uq_price_stock_ts_interval"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    interval: Mapped[str] = mapped_column(String(10), nullable=False, default="1d")  # 1d / 1h / 5m
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    adj_close: Mapped[float | None] = mapped_column(Float)  # 수정 종가

    stock: Mapped["Stock"] = relationship(back_populates="price_history")

    def __repr__(self) -> str:
        return f"<PriceHistory {self.stock_id} {self.timestamp} C={self.close}>"


# ─────────────────────────────────────────────
# 3. 기술적 지표 캐시
# ─────────────────────────────────────────────
class TechnicalIndicator(Base):
    """
    일별 계산된 기술적 지표 캐시
    - RSI (상대강도지수)
    - MACD / Signal / Histogram
    - 볼린저 밴드 (상단/중단/하단)
    - 이동평균선 (MA20, MA50, MA200)
    """
    __tablename__ = "technical_indicators"
    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_indicator_stock_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    # RSI
    rsi_14: Mapped[float | None] = mapped_column(Float)

    # MACD
    macd: Mapped[float | None] = mapped_column(Float)
    macd_signal: Mapped[float | None] = mapped_column(Float)
    macd_hist: Mapped[float | None] = mapped_column(Float)

    # 볼린저 밴드
    bb_upper: Mapped[float | None] = mapped_column(Float)
    bb_middle: Mapped[float | None] = mapped_column(Float)
    bb_lower: Mapped[float | None] = mapped_column(Float)

    # 이동평균
    ma_20: Mapped[float | None] = mapped_column(Float)
    ma_50: Mapped[float | None] = mapped_column(Float)
    ma_200: Mapped[float | None] = mapped_column(Float)

    # 거래량 이동평균
    volume_ma_20: Mapped[float | None] = mapped_column(Float)

    # ADX (평균 방향성 지수)
    adx_14: Mapped[float | None] = mapped_column(Float)

    # ATR (평균 진정 범위)
    atr_14: Mapped[float | None] = mapped_column(Float)

    # OBV (On-Balance Volume)
    obv: Mapped[float | None] = mapped_column(Float, default=None)

    # Stochastic RSI
    stoch_rsi_k: Mapped[float | None] = mapped_column(Float, default=None)
    stoch_rsi_d: Mapped[float | None] = mapped_column(Float, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="indicators")


# ─────────────────────────────────────────────
# 4. 포트폴리오 보유 종목
# ─────────────────────────────────────────────
class PortfolioHolding(Base):
    """
    현재 보유 중인 종목 정보
    매수/매도 거래가 발생할 때마다 업데이트됩니다.
    """
    __tablename__ = "portfolio_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stocks.id"), unique=True, nullable=False
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)            # 보유 수량
    avg_buy_price: Mapped[float] = mapped_column(Float, nullable=False)       # 평균 매수가
    total_invested: Mapped[float] = mapped_column(Float, nullable=False)      # 총 투자금액
    current_price: Mapped[float | None] = mapped_column(Float)               # 현재가 (주기적 업데이트)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float)              # 평가손익
    unrealized_pnl_pct: Mapped[float | None] = mapped_column(Float)          # 수익률 (%)
    first_bought_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    stock: Mapped["Stock"] = relationship(back_populates="holdings")

    def __repr__(self) -> str:
        return f"<Holding {self.stock_id} qty={self.quantity} avg={self.avg_buy_price}>"


# ─────────────────────────────────────────────
# 5. 거래 내역
# ─────────────────────────────────────────────
class Transaction(Base):
    """
    매수(BUY) / 매도(SELL) 거래 내역
    포트폴리오 손익 계산의 원천 데이터입니다.
    """
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(4), nullable=False)   # 'BUY' | 'SELL'
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)       # 체결 가격
    total_amount: Mapped[float] = mapped_column(Float, nullable=False) # 체결 총액
    fee: Mapped[float] = mapped_column(Float, default=0.0)            # 수수료
    realized_pnl: Mapped[float | None] = mapped_column(Float)        # 실현 손익 (SELL 시)
    note: Mapped[str | None] = mapped_column(Text)                    # 메모 (AI 추천 근거 등)
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction {self.action} {self.stock_id} qty={self.quantity} @{self.price}>"


# ─────────────────────────────────────────────
# 6. AI 매수 추천 이력
# ─────────────────────────────────────────────
class AIRecommendation(Base):
    """
    Claude AI가 생성한 일별 매수 추천 기록
    추천 근거(reasoning)와 신뢰도(confidence)를 함께 저장합니다.
    """
    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    recommendation_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    # 추천 내용
    action: Mapped[str] = mapped_column(String(10), nullable=False)   # 'STRONG_BUY' | 'BUY' | 'HOLD'
    confidence: Mapped[float] = mapped_column(Float, nullable=False)   # 신뢰도 0.0 ~ 1.0
    target_price: Mapped[float | None] = mapped_column(Float)         # 목표 주가
    stop_loss: Mapped[float | None] = mapped_column(Float)            # 손절 기준가

    # AI 분석 내용
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)       # 추천 근거 (AI 응답 원문)
    technical_score: Mapped[float | None] = mapped_column(Float)      # 기술적 분석 점수
    fundamental_score: Mapped[float | None] = mapped_column(Float)    # 기본적 분석 점수
    sentiment_score: Mapped[float | None] = mapped_column(Float)      # 시장 심리 점수

    # 추천 당시 주가
    price_at_recommendation: Mapped[float | None] = mapped_column(Float)

    # 결과 추적
    is_executed: Mapped[bool] = mapped_column(Boolean, default=False)  # 실제 매수 여부
    outcome_price: Mapped[float | None] = mapped_column(Float)         # 결과 확인 시점 주가
    outcome_return: Mapped[float | None] = mapped_column(Float)        # 실현 수익률

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="recommendations")

    def __repr__(self) -> str:
        return f"<AIRecommendation {self.stock_id} {self.action} conf={self.confidence:.2f}>"


# ─────────────────────────────────────────────
# 7. AI 매도 신호
# ─────────────────────────────────────────────
class SellSignal(Base):
    """
    보유 종목에 대한 AI 매도 신호
    매일 보유 종목을 분석하여 최적 매도 타이밍을 제시합니다.
    """
    __tablename__ = "sell_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    signal_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    # 신호 내용
    signal: Mapped[str] = mapped_column(String(15), nullable=False)   # 'STRONG_SELL' | 'SELL' | 'HOLD'
    urgency: Mapped[str] = mapped_column(String(10), default="NORMAL") # 'HIGH' | 'NORMAL' | 'LOW'
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # 분석 내용
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_sell_price: Mapped[float | None] = mapped_column(Float)  # 제안 매도가

    # 신호 당시 상태
    current_price: Mapped[float | None] = mapped_column(Float)
    current_pnl_pct: Mapped[float | None] = mapped_column(Float)       # 현재 수익률 (%)

    is_acted_upon: Mapped[bool] = mapped_column(Boolean, default=False) # 매도 실행 여부
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="sell_signals")

    def __repr__(self) -> str:
        return f"<SellSignal {self.stock_id} {self.signal} conf={self.confidence:.2f}>"


# ─────────────────────────────────────────────
# 8. 가격 알림 설정
# ─────────────────────────────────────────────
class PriceAlert(Base):
    """
    종목별 가격 알림 조건 설정
    손절가(STOP_LOSS), 목표가(TARGET_PRICE), 거래량 급등(VOLUME_SURGE) 조건 감시
    """
    __tablename__ = "price_alerts"
    __table_args__ = (
        Index("ix_price_alerts_stock_type", "stock_id", "alert_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)  # STOP_LOSS | TARGET_PRICE | VOLUME_SURGE
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)  # 기준 가격 또는 배수
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    stock: Mapped["Stock"] = relationship(back_populates="price_alerts")

    def __repr__(self) -> str:
        return f"<PriceAlert {self.stock_id} {self.alert_type} @{self.threshold_value}>"


# ─────────────────────────────────────────────
# 9. 알림 발화 이력
# ─────────────────────────────────────────────
class AlertHistory(Base):
    """
    실제 발화된 알림 이력
    중복 방지 및 알림 감사 로그로 활용됩니다.
    """
    __tablename__ = "alert_history"
    __table_args__ = (
        Index("ix_alert_history_stock_type_time", "stock_id", "alert_type", "triggered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False, index=True)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_price: Mapped[float | None] = mapped_column(Float)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stock: Mapped["Stock"] = relationship(back_populates="alert_history")

    def __repr__(self) -> str:
        return f"<AlertHistory {self.stock_id} {self.alert_type} @{self.triggered_at}>"


# ─────────────────────────────────────────────
# 10. 시장 뉴스 / 이벤트
# ─────────────────────────────────────────────
class MarketNews(Base):
    """
    yfinance 또는 외부 API에서 수집한 시장 뉴스
    AI 분석 시 컨텍스트 데이터로 활용합니다.
    """
    __tablename__ = "market_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str | None] = mapped_column(String(20), index=True)  # None = 시장 전반
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000), unique=True)
    source: Mapped[str | None] = mapped_column(String(100))
    sentiment: Mapped[float | None] = mapped_column(Float)  # -1.0 (부정) ~ +1.0 (긍정)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<MarketNews {self.ticker} '{self.title[:40]}...'>"
