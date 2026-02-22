"""
AI 매도 신호 분석 모듈
Google Gemini API를 사용하여 보유 종목의 매도 타이밍을 분석하고
SellSignal 테이블에 저장합니다.
"""
import json
from datetime import datetime, timedelta, timezone

from loguru import logger

from config.settings import settings
from database.connection import get_db
from database.models import AIRecommendation, MarketNews, PriceHistory, SellSignal, Stock, TechnicalIndicator
from portfolio.portfolio_manager import portfolio_manager

SELL_SYSTEM_PROMPT = """You are an expert portfolio risk manager specializing in exit strategy optimization.
Analyze the provided holding data and generate a sell signal recommendation.

CRITICAL: Respond ONLY with valid JSON matching this exact schema:
{
    "signal": "STRONG_SELL" | "SELL" | "HOLD",
    "urgency": "HIGH" | "NORMAL" | "LOW",
    "confidence": <float 0.0-1.0>,
    "suggested_sell_price": <float or null>,
    "reasoning": "<Korean string, max 500 chars>",
    "exit_strategy": "<Korean string describing exit approach>",
    "risk_factors": ["<risk1>", "<risk2>", ...]
}

Guidelines:
- STRONG_SELL + HIGH urgency: immediate exit recommended (stop-loss breach, severe deterioration)
- STRONG_SELL + NORMAL: sell within 1-2 days
- SELL: consider selling within a week
- HOLD: maintain position, no immediate action needed
- Consider: current PnL %, holding period, RSI (>70 = overbought), MACD trend, Bollinger Band position
- reasoning and exit_strategy must be in Korean"""


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
        self._model = None

    def _get_model(self):
        """Gemini 모델 지연 초기화 (캐싱)"""
        if self._model is not None:
            return self._model

        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=SELL_SYSTEM_PROMPT,
                generation_config=genai.GenerationConfig(
                    temperature=settings.AI_TEMPERATURE,
                    max_output_tokens=settings.AI_MAX_TOKENS,
                    response_mime_type="application/json",
                ),
            )
            logger.debug(f"[매도 분석] Gemini 모델 초기화 완료: {settings.GEMINI_MODEL}")
        except ImportError:
            raise RuntimeError(
                "google-generativeai 패키지가 설치되지 않았습니다. "
                "pip install google-generativeai 로 설치하세요."
            )
        return self._model

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

        # ATR(14) 계산 [J]
        atr_value = None
        if len(price_rows) >= 15:
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
                logger.debug(f"[{ticker}] ATR 계산 실패 (무시): {atr_err}")

        # 최신 기술적 지표
        ind = (
            db.query(TechnicalIndicator)
            .filter(TechnicalIndicator.stock_id == stock.id)
            .order_by(TechnicalIndicator.date.desc())
            .first()
        )

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

        # 보유 기간 계산
        holding_days = 0
        if holding_info.get("first_bought_at"):
            try:
                bought_at = datetime.strptime(holding_info["first_bought_at"], "%Y-%m-%d")
                holding_days = (datetime.now() - bought_at).days
            except (ValueError, TypeError):
                holding_days = 0

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

        # 뉴스
        if news:
            prompt_parts.append("## Recent News:")
            for n in news:
                sentiment_str = f"sentiment={n['sentiment']}" if n["sentiment"] is not None else "sentiment=N/A"
                prompt_parts.append(f"- [{n.get('published_at', 'N/A')}] {n['title']} ({sentiment_str})")
            prompt_parts.append("")

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
            atr_stop = current_price - (2 * atr)
            atr_pct = (atr_stop - current_price) / current_price * 100
            prompt_parts.extend([
                "",
                "## Volatility-Based Stop Loss (ATR):",
                f"- ATR(14): ${atr:.2f}",
                f"- ATR 기반 손절가 (2×ATR): ${atr_stop:.2f} (현재가 대비 {atr_pct:.1f}%)",
                "",
            ])

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

        prompt_parts.append("\nBased on all the above data, provide your sell signal recommendation as JSON.")

        return "\n".join(prompt_parts)

    def _parse_response(self, text: str) -> dict:
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
            model = self._get_model()
        except RuntimeError as e:
            logger.error(f"[매도 분석] 모델 초기화 실패: {e}")
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
                response = model.generate_content(prompt)
                parsed = self._parse_response(response.text)
            except Exception as e:
                logger.error(f"[{ticker}] 매도 AI API 호출 실패: {e}")
                return None

            # DB 저장
            sig = SellSignal(
                stock_id=stock.id,
                signal_date=datetime.now(timezone.utc).replace(tzinfo=None),
                signal=parsed["signal"],
                urgency=parsed["urgency"],
                confidence=parsed["confidence"],
                reasoning=parsed["reasoning"],
                suggested_sell_price=parsed.get("suggested_sell_price"),
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
        logger.info(f"[매도 분석] 보유 종목 {len(holdings)}개 분석 시작")

        for h in holdings:
            ticker = h["ticker"]
            try:
                sig = self.analyze_holding(ticker, h)
                results[ticker] = sig.signal if sig else "ERROR"
            except Exception as e:
                logger.error(f"[{ticker}] 매도 분석 중 예외: {e}")
                results[ticker] = "ERROR"

        sell_count = sum(1 for s in results.values() if s in ("SELL", "STRONG_SELL"))
        logger.info(f"[매도 분석] 완료 — 매도 신호: {sell_count}/{len(holdings)}개")
        return results

    def get_active_sell_signals(self) -> list[dict]:
        """
        오늘의 매도 신호 목록을 반환합니다 (대시보드용).
        SELL/STRONG_SELL이 먼저, urgency=HIGH가 우선 정렬됩니다.
        """
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        urgency_order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
        signal_order = {"STRONG_SELL": 0, "SELL": 1, "HOLD": 2}

        with get_db() as db:
            sigs = (
                db.query(SellSignal)
                .filter(SellSignal.signal_date >= today_start)
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
