"""
AI 매도 신호 분석 모듈
Google Gemini API를 사용하여 보유 종목의 매도 타이밍을 분석하고
SellSignal 테이블에 저장합니다.
"""
import json
import time
from datetime import datetime, timedelta, timezone

from loguru import logger

from config.settings import settings
from database.connection import get_db
from database.models import AIRecommendation, MarketNews, PriceHistory, SellSignal, Stock, TechnicalIndicator
from portfolio.portfolio_manager import portfolio_manager

SELL_SYSTEM_PROMPT = """You are an expert portfolio risk manager specializing in exit strategy optimization.
Analyze the provided holding data using the 3-pillar scoring framework below.

## SCORING FRAMEWORK

### Pillar 1: Technical Deterioration Score (0-10, weight 0.45)
| Score | Criteria |
|-------|----------|
| 8-10  | RSI>75 + MACD dead cross + price below MA20 & MA50 + high volume selling |
| 6-7   | 2-3 bearish signals (e.g., RSI>70, MACD histogram declining, below MA20) |
| 5     | Mixed signals — some bearish, some bullish |
| 3-4   | Mostly bullish — above MAs, RSI healthy, MACD positive |
| 0-2   | Strong uptrend — all signals aligned bullish |

### Pillar 2: Position Risk Score (0-10, weight 0.35)
| Score | Criteria |
|-------|----------|
| 8-10  | Loss > -10% OR drawdown from high > 15% OR stop-loss breached |
| 6-7   | Loss -5% to -10% OR drawdown 10-15% from high |
| 5     | Breakeven or small gain/loss (<5%) |
| 3-4   | Moderate gain (5-15%) with no trailing stop breach |
| 0-2   | Large gain (>15%) with strong uptrend intact |

### Pillar 3: Fundamental/Sentiment Score (0-10, weight 0.20)
| Score | Criteria |
|-------|----------|
| 8-10  | Severe negative catalyst (earnings miss, downgrade, sector collapse) |
| 5     | No significant news or mixed sentiment |
| 0-2   | Strong positive catalyst supporting hold |

### Derive sell_pressure
sell_pressure = (technical_score * 0.45) + (position_risk_score * 0.35) + (fundamental_score * 0.20)
- STRONG_SELL: sell_pressure >= 7.0
- SELL: sell_pressure >= 5.5
- HOLD: sell_pressure < 5.5

### Urgency
- HIGH: stop-loss breached, loss > -10%, or sell_pressure >= 8.0
- NORMAL: sell_pressure 5.5-8.0
- LOW: sell_pressure < 5.5

CRITICAL: Respond ONLY with valid JSON:
{
    "signal": "STRONG_SELL" | "SELL" | "HOLD",
    "urgency": "HIGH" | "NORMAL" | "LOW",
    "confidence": <float 0.0-1.0>,
    "technical_score": <float 0.0-10.0>,
    "position_risk_score": <float 0.0-10.0>,
    "fundamental_score": <float 0.0-10.0>,
    "sell_pressure": <float 0.0-10.0>,
    "suggested_sell_price": <float or null>,
    "reasoning": "<max 500 chars, cite specific numbers from input>",
    "exit_strategy": "<string: IMMEDIATE | LIMIT_SELL | SCALE_OUT | HOLD_WITH_STOP>",
    "risk_factors": ["<risk1>", "<risk2>", ...]
}

RULES:
- All text in English
- reasoning MUST cite at least 2 specific numbers from input data
- Compute sell_pressure from the 3 pillar scores, then derive signal"""


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _bb_position(current_price: float, bb_upper: float | None, bb_lower: float | None) -> str:
    """현재 가격의 볼린저밴드 내 위치를 텍스트로 반환합니다."""
    if not bb_upper or not bb_lower or (bb_upper - bb_lower) == 0:
        return "N/A"
    pct = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
    if pct >= 95:
        return f"{pct:.1f}% (상단 돌파 - 과매수 위험)"
    elif pct >= 80:
        return f"{pct:.1f}% (상단 근접)"
    elif pct <= 5:
        return f"{pct:.1f}% (하단 이탈 - 과매도)"
    elif pct <= 20:
        return f"{pct:.1f}% (하단 근접)"
    else:
        return f"{pct:.1f}% (중간)"


def _pct_diff(current: float, reference: float | None, label: str) -> str | None:
    """현재가와 기준값의 이격도를 반환합니다."""
    if reference is None or reference == 0:
        return None
    diff = (current - reference) / reference * 100
    return f"{label}: {diff:+.2f}%"


# ── 클래스 ─────────────────────────────────────────────────────────────────────

class SellAnalyzer:
    """Google Gemini 기반 매도 신호 분석기"""

    def __init__(self):
        self._client = None

    def _get_client(self):
        """Gemini 클라이언트 지연 초기화 (캐싱)"""
        if self._client is not None:
            return self._client

        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

        try:
            from google import genai
            self._client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
            )
            logger.debug(f"[매도 분석] Gemini 클라이언트 초기화 완료: {settings.GEMINI_MODEL}")
        except ImportError:
            raise RuntimeError(
                "google-genai 패키지가 설치되지 않았습니다. "
                "pip install google-genai 로 설치하세요."
            )
        return self._client

    def _build_sell_context(self, ticker: str, holding_info: dict, db) -> dict:
        """보유 정보 + 기술적 지표 + 뉴스를 결합한 매도 분석 컨텍스트를 구성합니다."""
        stock = db.query(Stock).filter(Stock.ticker == ticker).first()
        if stock is None:
            return {}

        # 최근 20일 일봉 (high, low 포함 — ATR 계산용) [J]
        price_rows = (
            db.query(PriceHistory)
            .filter(
                PriceHistory.stock_id == stock.id,
                PriceHistory.interval == "1d",
            )
            .order_by(PriceHistory.timestamp.desc())
            .limit(20)
            .all()
        )
        price_rows = list(reversed(price_rows))

        prices = [
            {
                "date": r.timestamp.strftime("%Y-%m-%d"),
                "high": round(r.high, 2),
                "low": round(r.low, 2),
                "close": round(r.close, 2),
                "volume": r.volume,
            }
            for r in price_rows
        ]

        # 최신 기술적 지표
        ind = (
            db.query(TechnicalIndicator)
            .filter(TechnicalIndicator.stock_id == stock.id)
            .order_by(TechnicalIndicator.date.desc())
            .first()
        )

        # ATR(14): DB 캐시 우선, 없으면 재계산 [J]
        atr_value = None
        if ind and ind.atr_14 is not None:
            atr_value = float(ind.atr_14)
        elif len(price_rows) >= 15:
            try:
                import pandas as pd
                import ta
                df_atr = pd.DataFrame([
                    {"high": r.high, "low": r.low, "close": r.close}
                    for r in price_rows
                ])
                atr_series = ta.volatility.AverageTrueRange(
                    high=df_atr["high"],
                    low=df_atr["low"],
                    close=df_atr["close"],
                    window=14,
                ).average_true_range()
                last_atr = atr_series.iloc[-1]
                atr_value = float(last_atr) if not pd.isna(last_atr) else None
            except Exception as atr_err:
                logger.debug(f"[{ticker}] ATR 재계산 실패 (무시): {atr_err}")

        # AI 추천 stop_loss 조회 [D]
        ai_stop_loss = None
        latest_rec = (
            db.query(AIRecommendation)
            .filter(
                AIRecommendation.stock_id == stock.id,
                AIRecommendation.stop_loss.isnot(None),
                AIRecommendation.action.in_(["BUY", "STRONG_BUY"]),
            )
            .order_by(AIRecommendation.recommendation_date.desc())
            .first()
        )
        if latest_rec:
            ai_stop_loss = latest_rec.stop_loss

        # 최신 뉴스 7건 (30일 이내 필터) [N]
        news_cutoff = datetime.now() - timedelta(days=30)
        news_rows = (
            db.query(MarketNews)
            .filter(
                MarketNews.ticker == ticker,
                MarketNews.published_at >= news_cutoff,
            )
            .order_by(MarketNews.published_at.desc())
            .limit(7)
            .all()
        )
        news = [
            {
                "title": n.title,
                "sentiment": round(n.sentiment, 3) if n.sentiment else None,
                "published_at": n.published_at.strftime("%Y-%m-%d") if n.published_at else None,
            }
            for n in news_rows
        ]

        # 기본 재무 데이터 (매도 분석용)
        fundamentals = {}
        try:
            import yfinance as yf
            yt = yf.Ticker(ticker)
            info = yt.info
            fundamentals = {
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "earnings_growth": info.get("earningsGrowth"),
                "recommendation_key": info.get("recommendationKey"),
            }
        except Exception:
            pass

        # 보유 기간 계산
        holding_days = 0
        if holding_info.get("first_bought_at"):
            try:
                bought_at = datetime.strptime(holding_info["first_bought_at"], "%Y-%m-%d")
                holding_days = (datetime.now() - bought_at).days
            except (ValueError, TypeError):
                holding_days = 0

        # ── 보유기간 중 최고가 (high_watermark) 조회 ──
        high_watermark = None
        drawdown_from_high_pct = None
        current_price_val = holding_info.get("current_price", 0)

        if holding_info.get("first_bought_at"):
            try:
                from sqlalchemy import func, and_
                bought_at = datetime.strptime(holding_info["first_bought_at"], "%Y-%m-%d")
                hw_row = (
                    db.query(func.max(PriceHistory.high))
                    .filter(
                        and_(
                            PriceHistory.stock_id == stock.id,
                            PriceHistory.interval == "1d",
                            PriceHistory.timestamp >= bought_at,
                        )
                    )
                    .scalar()
                )
                if hw_row and hw_row > 0:
                    high_watermark = round(hw_row, 2)
                    if current_price_val and current_price_val > 0:
                        drawdown_from_high_pct = round(
                            (current_price_val - hw_row) / hw_row * 100, 2
                        )
            except Exception as hw_err:
                logger.debug(f"[{ticker}] high_watermark 조회 실패 (무시): {hw_err}")

        # 시장 국면 데이터 (SPY, QQQ, ^VIX)
        market_context = {}
        try:
            from data_fetcher.market_data import market_fetcher as _mf
            for symbol in ["SPY", "QQQ", "^VIX"]:
                data = _mf.fetch_realtime_price(symbol)
                if data:
                    market_context[symbol] = {
                        "price": data["price"],
                        "change_pct": data["change_pct"],
                    }
        except Exception as e:
            logger.debug(f"[{ticker}] 시장 국면 데이터 조회 실패 (무시): {e}")

        return {
            "stock": {
                "ticker": stock.ticker,
                "name": stock.name,
                "sector": stock.sector,
            },
            "holding": {
                "quantity": holding_info.get("quantity", 0),
                "avg_buy_price": holding_info.get("avg_buy_price", 0),
                "current_price": holding_info.get("current_price", 0),
                "total_invested": holding_info.get("total_invested", 0),
                "current_value": holding_info.get("current_value", 0),
                "unrealized_pnl": holding_info.get("unrealized_pnl", 0),
                "unrealized_pnl_pct": holding_info.get("unrealized_pnl_pct", 0),
                "holding_days": holding_days,
            },
            "indicators": ind,
            "prices": prices,
            "news": news,
            "ai_stop_loss": ai_stop_loss,
            "atr": atr_value,
            "high_watermark": high_watermark,
            "drawdown_from_high_pct": drawdown_from_high_pct,
            "market_context": market_context,
            "fundamentals": fundamentals,
        }

    def _build_sell_prompt(self, context: dict) -> str:
        """매도 분석용 프롬프트를 생성합니다."""
        stock = context.get("stock", {})
        holding = context.get("holding", {})
        ind = context.get("indicators")
        prices = context.get("prices", [])
        news = context.get("news", [])

        current_price = holding.get("current_price", 0)
        avg_buy_price = holding.get("avg_buy_price", 0)
        pnl_pct = holding.get("unrealized_pnl_pct", 0)
        pnl_dollar = holding.get("unrealized_pnl", 0)
        holding_days = holding.get("holding_days", 0)

        prompt_parts = [
            f"## Holding Analysis: {stock.get('ticker')} - {stock.get('name')}",
            f"Sector: {stock.get('sector')}",
            "",
            "## Position Details:",
            f"- Quantity: {holding.get('quantity')} shares",
            f"- Avg Buy Price: ${avg_buy_price:.2f}",
            f"- Current Price: ${current_price:.2f}",
            f"- Total Invested: ${holding.get('total_invested', 0):.2f}",
            f"- Current Value: ${holding.get('current_value', 0):.2f}",
            f"- Unrealized PnL: ${pnl_dollar:+.2f} ({pnl_pct:+.2f}%)",
            f"- Holding Period: {holding_days} days",
            "",
        ]

        # 기술적 경고 신호
        warnings = []
        if ind:
            rsi = ind.rsi_14
            macd_hist = ind.macd_hist
            bb_upper = ind.bb_upper
            bb_lower = ind.bb_lower
            ma_20 = ind.ma_20
            ma_50 = ind.ma_50

            if rsi is not None:
                if rsi > 70:
                    warnings.append(f"⚠️ RSI={rsi:.1f} (과매수 구간 — 매도 고려)")
                elif rsi < 30:
                    warnings.append(f"✅ RSI={rsi:.1f} (과매도 — 반등 가능성)")
                else:
                    warnings.append(f"RSI={rsi:.1f} (중립)")

            if macd_hist is not None:
                if macd_hist < 0:
                    warnings.append(f"⚠️ MACD Histogram={macd_hist:.4f} (음수 — 하락 모멘텀)")
                else:
                    warnings.append(f"✅ MACD Histogram={macd_hist:.4f} (양수 — 상승 모멘텀)")

            bb_pos = _bb_position(current_price, bb_upper, bb_lower)
            warnings.append(f"볼린저밴드 위치: {bb_pos}")

            ma20_diff = _pct_diff(current_price, ma_20, "vs MA20")
            ma50_diff = _pct_diff(current_price, ma_50, "vs MA50")
            if ma20_diff:
                warnings.append(ma20_diff)
            if ma50_diff:
                warnings.append(ma50_diff)

        if warnings:
            prompt_parts.append("## Technical Warning Signals:")
            prompt_parts.extend([f"- {w}" for w in warnings])
            prompt_parts.append("")

        # 최근 가격 추세
        if prices:
            prompt_parts.append("## Recent Price Trend (last 10 days):")
            prompt_parts.append(json.dumps(prices[-10:], indent=2))
            prompt_parts.append("")

        # 시장 국면
        market_ctx = context.get("market_context", {})
        if market_ctx:
            market_lines = ["## Market Context:"]
            spy = market_ctx.get("SPY")
            qqq = market_ctx.get("QQQ")
            vix = market_ctx.get("^VIX")
            if spy:
                trend = "상승" if spy["change_pct"] > 0 else "하락"
                market_lines.append(f"- SPY: ${spy['price']:.2f} ({spy['change_pct']:+.2f}%) — {trend}")
            if qqq:
                trend = "상승" if qqq["change_pct"] > 0 else "하락"
                market_lines.append(f"- QQQ: ${qqq['price']:.2f} ({qqq['change_pct']:+.2f}%) — {trend}")
            if vix:
                vix_level = "HIGH(공포)" if vix["price"] > 30 else ("ELEVATED(경계)" if vix["price"] > 20 else "LOW(안정)")
                market_lines.append(f"- VIX: {vix['price']:.2f} ({vix_level})")
            prompt_parts.extend(market_lines + [""])

        # 뉴스
        if news:
            prompt_parts.append("## Recent News:")
            for n in news:
                sentiment_str = f"sentiment={n['sentiment']}" if n["sentiment"] is not None else "sentiment=N/A"
                prompt_parts.append(f"- [{n.get('published_at', 'N/A')}] {n['title']} ({sentiment_str})")
            prompt_parts.append("")

        # 재무 데이터
        fundamentals = context.get("fundamentals", {})
        if fundamentals:
            fund_lines = ["## Fundamental Data:"]
            if fundamentals.get("pe_ratio"):
                fund_lines.append(f"- P/E (trailing): {fundamentals['pe_ratio']:.1f}")
            if fundamentals.get("forward_pe"):
                fund_lines.append(f"- P/E (forward): {fundamentals['forward_pe']:.1f}")
            if fundamentals.get("revenue_growth") is not None:
                fund_lines.append(f"- Revenue Growth: {fundamentals['revenue_growth']:.1%}")
            if fundamentals.get("earnings_growth") is not None:
                fund_lines.append(f"- Earnings Growth: {fundamentals['earnings_growth']:.1%}")
            if fundamentals.get("profit_margin") is not None:
                fund_lines.append(f"- Profit Margin: {fundamentals['profit_margin']:.1%}")
            if fundamentals.get("recommendation_key"):
                fund_lines.append(f"- Analyst Consensus: {fundamentals['recommendation_key']}")
            if len(fund_lines) > 1:
                prompt_parts.extend(fund_lines + [""])

        # AI 추천 stop_loss 우선 활용 [D]
        ai_stop_loss = context.get("ai_stop_loss")
        if ai_stop_loss and current_price:
            if current_price <= ai_stop_loss:
                prompt_parts.append(
                    f"🔴 CRITICAL: 현재가(${current_price:.2f})가 AI 추천 손절가(${ai_stop_loss:.2f}) 이하 — 즉각 손절 검토"
                )
            else:
                sl_pct = (current_price - ai_stop_loss) / current_price * 100
                prompt_parts.append(
                    f"ℹ️ AI 추천 손절가: ${ai_stop_loss:.2f} (현재가 대비 -{sl_pct:.1f}% 하락 시 손절)"
                )

        # ATR 기반 동적 손절가 제안 [J]
        atr = context.get("atr")
        if atr and current_price:
            atr_stop = current_price - (3 * atr)
            atr_pct = (atr_stop - current_price) / current_price * 100
            prompt_parts.extend([
                "",
                "## Volatility-Based Stop Loss (ATR):",
                f"- ATR(14): ${atr:.2f}",
                f"- ATR 기반 손절가 (3×ATR, Chandelier Exit): ${atr_stop:.2f} (현재가 대비 {atr_pct:.1f}%)",
                "",
            ])

        # Trailing Stop Analysis (ATR-based dynamic trailing stop)
        high_watermark = context.get("high_watermark")
        drawdown_from_high_pct = context.get("drawdown_from_high_pct")
        current_price_val = holding.get("current_price", 0)
        if high_watermark is not None:
            prompt_parts.extend([
                "",
                "## Trailing Stop Analysis:",
                f"- High Watermark (holding period max): ${high_watermark:.2f}",
                f"- Drawdown from high: {drawdown_from_high_pct:+.2f}%",
            ])

            # 동적 트레일링 스톱 (ATR 기반)
            atr = context.get("atr")
            if drawdown_from_high_pct is not None:
                if atr and current_price_val > 0:
                    atr_pct = (3 * atr / current_price_val) * 100
                    trailing_threshold = max(atr_pct, 5.0)   # 최소 5%
                    trailing_threshold = min(trailing_threshold, 20.0)  # 최대 20%
                else:
                    trailing_threshold = 10.0  # ATR 없으면 기존 10% 사용

                if abs(drawdown_from_high_pct) >= trailing_threshold:
                    prompt_parts.append(
                        f"⚠️ CRITICAL: Price down {abs(drawdown_from_high_pct):.1f}% from high watermark. "
                        f"Dynamic trailing stop ({trailing_threshold:.1f}%, based on 3x ATR) BREACHED. "
                        f"Immediate sell review required!"
                    )
                elif abs(drawdown_from_high_pct) >= trailing_threshold * 0.7:
                    prompt_parts.append(
                        f"⚠️ WARNING: Price down {abs(drawdown_from_high_pct):.1f}% from high watermark, "
                        f"approaching trailing stop ({trailing_threshold:.1f}%). Monitor closely."
                    )

            prompt_parts.append("")

        # PnL 기반 특별 경고 (AI stop_loss 보조 기준) [D, M]
        if pnl_pct <= -10:
            if not ai_stop_loss:
                prompt_parts.append(
                    f"⚠️ CRITICAL: Position is down {abs(pnl_pct):.1f}%. Stop-loss -10% 기준 초과 — 손절 검토 필요."
                )
        elif pnl_pct > 0:
            # 보유기간별 차등 이익실현 임계값 [M]
            if holding_days < 30 and pnl_pct >= 15:
                prompt_parts.append(
                    f"💰 SHORT-TERM ALERT: {holding_days}일 보유 중 +{pnl_pct:.1f}% 단기 급등 — 이익실현 고려 (단기 임계값: +15%)"
                )
            elif 30 <= holding_days <= 180 and pnl_pct >= 25:
                prompt_parts.append(
                    f"💰 MID-TERM NOTE: {holding_days}일 보유 중 +{pnl_pct:.1f}% 달성 — 이익실현 고려 (중기 임계값: +25%)"
                )
            elif holding_days > 180 and pnl_pct >= 40:
                prompt_parts.append(
                    f"💰 LONG-TERM NOTE: {holding_days}일 보유 중 +{pnl_pct:.1f}% 달성 — 이익실현 고려 (장기 임계값: +40%)"
                )

        # 세금 최적화 안내 (미국 장기 양도소득세 기준 365일)
        if 300 <= holding_days <= 365 and pnl_pct > 10:
            prompt_parts.append(
                f"TAX NOTE: {365 - holding_days} days until long-term capital gains threshold (365 days). "
                f"Current gain: +{pnl_pct:.1f}%. Consider holding unless technical breakdown is imminent."
            )
            prompt_parts.append("")

        prompt_parts.append("\nBased on all the above data, provide your sell signal recommendation as JSON.")

        return "\n".join(prompt_parts)

    def _parse_response(self, text: str, current_price: float | None = None) -> dict:
        """AI 응답을 파싱하고 필수 필드를 검증합니다."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"JSON 파싱 실패: {text[:200]}")

        required_fields = ["signal", "urgency", "confidence", "reasoning"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"필수 필드 누락: {field}")

        valid_signals = {"STRONG_SELL", "SELL", "HOLD"}
        if data["signal"] not in valid_signals:
            raise ValueError(f"유효하지 않은 signal: {data['signal']}")

        valid_urgency = {"HIGH", "NORMAL", "LOW"}
        if data["urgency"] not in valid_urgency:
            data["urgency"] = "NORMAL"

        confidence = float(data["confidence"])
        data["confidence"] = max(0.0, min(1.0, confidence))

        data.setdefault("suggested_sell_price", None)
        data.setdefault("exit_strategy", "")
        data.setdefault("risk_factors", [])
        data.setdefault("technical_score", None)
        data.setdefault("position_risk_score", None)
        data.setdefault("fundamental_score", None)
        data.setdefault("sell_pressure", None)

        # score 필드 범위 검증 (0.0~10.0 클램핑)
        for score_field in ["technical_score", "position_risk_score", "fundamental_score", "sell_pressure"]:
            val = data.get(score_field)
            if val is not None:
                data[score_field] = max(0.0, min(10.0, float(val)))

        # sell_pressure 일관성 검증
        sp = data.get("sell_pressure")
        ts = data.get("technical_score")
        pr = data.get("position_risk_score")
        fs = data.get("fundamental_score")
        if sp is not None and ts is not None and pr is not None and fs is not None:
            expected_sp = ts * 0.45 + pr * 0.35 + fs * 0.20
            if abs(sp - expected_sp) > 1.5:
                logger.warning(f"sell_pressure 불일치: {sp:.1f} vs 예상 {expected_sp:.1f}")
                data["sell_pressure"] = round(expected_sp, 2)

        # suggested_sell_price 합리성 검증
        if current_price is not None and current_price > 0:
            sp = data.get("suggested_sell_price")
            if sp is not None:
                if not (current_price * 0.5 <= sp <= current_price * 2.0):
                    logger.warning(
                        f"suggested_sell_price ${sp} 범위 초과 (현재가 ${current_price}의 0.5~2.0배) → None"
                    )
                    data["suggested_sell_price"] = None

        return data

    def analyze_holding(self, ticker: str, holding_info: dict) -> SellSignal | None:
        """
        보유 종목 하나를 분석하고 SellSignal을 DB에 저장합니다.

        Args:
            ticker: 종목 코드
            holding_info: portfolio_manager.get_holdings() 반환값의 개별 항목

        Returns:
            SellSignal 객체 또는 None (실패 시)
        """
        logger.info(f"[매도 분석] {ticker} 분석 시작 (PnL: {holding_info.get('unrealized_pnl_pct', 0):+.2f}%)")

        try:
            client = self._get_client()
        except RuntimeError as e:
            logger.error(f"[매도 분석] 클라이언트 초기화 실패: {e}")
            return None

        with get_db() as db:
            context = self._build_sell_context(ticker, holding_info, db)
            if not context:
                logger.warning(f"[{ticker}] 매도 분석 데이터 없음, 스킵")
                return None

            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                return None

            prompt = self._build_sell_prompt(context)

            try:
                from google.genai import types
                last_err = None
                for attempt in range(3):
                    try:
                        response = client.models.generate_content(
                            model=settings.GEMINI_MODEL,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=SELL_SYSTEM_PROMPT,
                                temperature=settings.AI_TEMPERATURE,
                                max_output_tokens=settings.AI_MAX_TOKENS,
                                thinking_config=types.ThinkingConfig(thinking_budget=1024),
                                response_mime_type="application/json",
                            ),
                        )
                        break
                    except Exception as api_err:
                        last_err = api_err
                        if attempt < 2:
                            import re as _re
                            wait_time = settings.GEMINI_BACKOFF_BASE * (2 ** attempt)
                            retry_match = _re.search(r"retry.*?(\d+)\.?\d*s", str(api_err), _re.IGNORECASE)
                            if retry_match:
                                wait_time = max(wait_time, int(retry_match.group(1)) + 1)
                            logger.warning(
                                f"[{ticker}] 매도 API 호출 실패 (시도 {attempt + 1}/3), "
                                f"{wait_time}초 후 재시도: {api_err}"
                            )
                            time.sleep(wait_time)
                        else:
                            raise last_err

                parsed = self._parse_response(
                    response.text,
                    current_price=holding_info.get("current_price"),
                )
            except Exception as e:
                logger.error(f"[{ticker}] 매도 AI API 호출 실패: {e}")
                return None

            # 신뢰도 임계값 미달 시 HOLD로 다운그레이드
            threshold = settings.SELL_CONFIDENCE_THRESHOLD
            if parsed["signal"] in ("SELL", "STRONG_SELL") and parsed["confidence"] < threshold:
                logger.info(
                    f"[{ticker}] 매도 신뢰도 {parsed['confidence']:.0%} < 임계값 {threshold:.0%} "
                    f"→ HOLD 다운그레이드 (원래: {parsed['signal']})"
                )
                parsed["signal"] = "HOLD"

            # DB 저장
            sig = SellSignal(
                stock_id=stock.id,
                signal_date=datetime.now(timezone.utc).replace(tzinfo=None),
                signal=parsed["signal"],
                urgency=parsed["urgency"],
                confidence=parsed["confidence"],
                reasoning=parsed["reasoning"],
                suggested_sell_price=parsed.get("suggested_sell_price"),
                technical_score=parsed.get("technical_score"),
                position_risk_score=parsed.get("position_risk_score"),
                fundamental_score=parsed.get("fundamental_score"),
                sell_pressure=parsed.get("sell_pressure"),
                exit_strategy=parsed.get("exit_strategy"),
                current_price=holding_info.get("current_price"),
                current_pnl_pct=holding_info.get("unrealized_pnl_pct"),
            )
            db.add(sig)
            db.flush()

            urgency_emoji = {"HIGH": "🔴", "NORMAL": "🟠", "LOW": "🟡"}.get(parsed["urgency"], "")
            signal_emoji = {"STRONG_SELL": "📉📉", "SELL": "📉", "HOLD": "⏸"}.get(parsed["signal"], "")
            logger.success(
                f"[매도 분석] {ticker} {signal_emoji} {parsed['signal']} "
                f"{urgency_emoji} urgency={parsed['urgency']} "
                f"(신뢰도: {parsed['confidence']:.0%})"
            )
            return sig

    def analyze_all_holdings(self) -> dict[str, str]:
        """
        현재 보유 종목 전체를 매도 분석합니다.

        Returns:
            {ticker: signal} 딕셔너리
        """
        holdings = portfolio_manager.get_holdings(update_prices=True)

        if not holdings:
            logger.info("[매도 분석] 보유 종목 없음")
            return {}

        results = {}

        import re as _re
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from google.api_core.exceptions import ResourceExhausted

        def _parse_retry_delay(err) -> int:
            m = _re.search(r"retry.*?(\d+)\.?\d*s", str(err), _re.IGNORECASE)
            return int(m.group(1)) + 1 if m else 0

        total = len(holdings)
        concurrency = settings.GEMINI_CONCURRENCY
        logger.info(f"[매도 분석] 보유 종목 {total}개 병렬 분석 시작 (동시 {concurrency}개)")

        def _analyze_one(idx_holding):
            idx, h = idx_holding
            ticker = h["ticker"]
            # 스태거 딜레이: 동시 요청 폭주 방지
            stagger = (idx % concurrency) * 1.0
            if stagger > 0:
                time.sleep(stagger)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    sig = self.analyze_holding(ticker, h)
                    return ticker, sig.signal if sig else "ERROR"
                except ResourceExhausted as e:
                    if attempt < max_retries - 1:
                        wait = max(settings.GEMINI_BACKOFF_BASE * (2 ** attempt), _parse_retry_delay(e))
                        logger.warning(f"[{ticker}] 매도 API 429. {wait}초 대기 후 재시도... ({attempt+1}/{max_retries})")
                        time.sleep(wait)
                    else:
                        logger.error(f"[{ticker}] 매도 최대 재시도 실패(429)")
                        return ticker, "ERROR"
                except Exception as e:
                    if '429' in str(e) and attempt < max_retries - 1:
                        wait = max(settings.GEMINI_BACKOFF_BASE * (2 ** attempt), _parse_retry_delay(e))
                        logger.warning(f"[{ticker}] 매도 API 429(str). {wait}초 대기 후 재시도...")
                        time.sleep(wait)
                    else:
                        logger.error(f"[{ticker}] 매도 분석 중 예외: {e}")
                        return ticker, "ERROR"
            return ticker, "ERROR"

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_analyze_one, (i, h)): h["ticker"]
                for i, h in enumerate(holdings)
            }
            for future in as_completed(futures):
                ticker, signal = future.result()
                results[ticker] = signal

        sell_count = sum(1 for s in results.values() if s in ("SELL", "STRONG_SELL"))
        logger.info(f"[매도 분석] 완료 — 매도 신호: {sell_count}/{len(holdings)}개")
        return results

    def get_active_sell_signals(self) -> list[dict]:
        """
        오늘의 매도 신호 목록을 반환합니다 (대시보드용).
        같은 종목에 대해 여러 번 분석한 경우 가장 최신 결과만 반환합니다.
        SELL/STRONG_SELL이 먼저, urgency=HIGH가 우선 정렬됩니다.
        """
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        urgency_order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
        signal_order = {"STRONG_SELL": 0, "SELL": 1, "HOLD": 2}

        with get_db() as db:
            from sqlalchemy import func as sa_func
            # 종목별 최신 매도 신호 ID만 추출
            latest_ids = (
                db.query(sa_func.max(SellSignal.id).label("max_id"))
                .filter(SellSignal.signal_date >= today_start)
                .group_by(SellSignal.stock_id)
                .subquery()
            )
            sigs = (
                db.query(SellSignal)
                .filter(SellSignal.id == latest_ids.c.max_id)
                .all()
            )

            results = []
            for s in sigs:
                stock = db.query(Stock).filter(Stock.id == s.stock_id).first()
                results.append({
                    "ticker": stock.ticker if stock else "?",
                    "name": stock.name if stock else "?",
                    "signal": s.signal,
                    "urgency": s.urgency,
                    "confidence": s.confidence,
                    "suggested_sell_price": s.suggested_sell_price,
                    "reasoning": s.reasoning,
                    "technical_score": s.technical_score,
                    "position_risk_score": s.position_risk_score,
                    "fundamental_score": s.fundamental_score,
                    "sell_pressure": s.sell_pressure,
                    "exit_strategy": s.exit_strategy,
                    "current_price": s.current_price,
                    "current_pnl_pct": s.current_pnl_pct,
                    "signal_date": s.signal_date.strftime("%Y-%m-%d %H:%M"),
                    "is_acted_upon": s.is_acted_upon,
                })

            results.sort(
                key=lambda x: (signal_order.get(x["signal"], 9), urgency_order.get(x["urgency"], 9))
            )

        return results


# 싱글톤 인스턴스
sell_analyzer = SellAnalyzer()
