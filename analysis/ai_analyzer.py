"""
AI 매수 추천 분석 모듈
Google Gemini API를 사용하여 관심 종목의 매수 추천을 생성하고
AIRecommendation 테이블에 저장합니다.
"""
import json
from datetime import datetime, timedelta, timezone

from loguru import logger

from config.settings import settings
from database.connection import get_db
from database.models import AIRecommendation, MarketNews, PriceHistory, Stock, TechnicalIndicator

SYSTEM_PROMPT = """You are a quantitative equity analyst running a systematic stock screening process for US equities.
Your task: evaluate whether a stock is a BUY candidate for a SWING TRADE (1-4 week holding period).

## DECISION FRAMEWORK (apply in this exact order)

### Step 1: Technical Score (0-10)
Evaluate ONLY from the provided indicator data:
| Score | Criteria |
|-------|----------|
| 8-10  | MACD golden cross + RSI 40-60 recovering + price above MA20 & MA50 + ADX>25 + volume confirmation |
| 6-7   | 2-3 bullish signals aligned (e.g., RSI<40 turning up + MACD histogram improving + above MA20) |
| 5     | Mixed signals — some bullish, some bearish, no clear direction |
| 3-4   | Mostly bearish — below key MAs, RSI declining, MACD negative |
| 0-2   | Strong bearish — RSI>70 diverging, MACD dead cross, below all MAs, high ADX downtrend |

### Step 2: Fundamental Score (0-10)
Evaluate ONLY from provided fundamental data. If a metric is missing, SKIP it (do not guess):
| Score | Criteria |
|-------|----------|
| 8-10  | Forward PE < sector avg, revenue growth >15%, positive FCF, ROE>15%, low debt |
| 6-7   | Reasonable valuation (PE<25), positive margins, manageable debt |
| 5     | Fair value or insufficient data (score 5.0 if mostly missing) |
| 3-4   | Expensive (PE>30) or declining margins or high debt |
| 0-2   | Severely overvalued or deteriorating fundamentals |

### Step 3: Sentiment Score (0-10)
Evaluate ONLY from provided news items and their sentiment values:
| Score | Criteria |
|-------|----------|
| 8-10  | Multiple recent positive catalysts (earnings beat, upgrade, product launch) |
| 5     | No significant news OR mixed/neutral (default if no news provided) |
| 0-2   | Severe negative catalyst (fraud, massive miss, sector collapse) |

### Step 4: Market Regime Adjustment
- VIX > 30: reduce confidence by 15-25%
- VIX > 25: reduce confidence by 5-15%
- SPY/QQQ both declining >1%: reduce confidence by 5-10%

### Step 5: Earnings Proximity Check
- Earnings within 7 days: cap confidence at 0.60
- Earnings within 3 days: cap confidence at 0.40

### Step 6: Derive Action
Calculate weighted_score = (technical * 0.45) + (fundamental * 0.30) + (sentiment * 0.25)
- STRONG_BUY: weighted_score >= 7.0 AND technical_score >= 6.5 AND confidence >= 0.75
- BUY: weighted_score >= 5.5 AND technical_score >= 4.5 AND confidence >= 0.55
- HOLD: below BUY thresholds
IMPORTANT: If technical_score >= 6 but you output HOLD, you MUST explain why in reasoning.

### Confidence Definition
confidence = probability of positive return within 2-4 weeks:
- 0.90+: All signals aligned, strong catalyst
- 0.75-0.89: Most signals bullish, minor concerns
- 0.55-0.74: Bullish lean but notable risks — sufficient for BUY
- 0.40-0.59: Mixed signals, uncertain
- <0.40: Mostly bearish or insufficient data

CRITICAL: Respond ONLY with valid JSON:
{
    "action": "STRONG_BUY" | "BUY" | "HOLD",
    "confidence": <float 0.0-1.0>,
    "target_price": <float — 2-4 week target within +3% to +15% of current price, or null>,
    "stop_loss": <float — within -2% to -8% of current price, or null>,
    "technical_score": <float 0.0-10.0>,
    "fundamental_score": <float 0.0-10.0>,
    "sentiment_score": <float 0.0-10.0>,
    "weighted_score": <float 0.0-10.0>,
    "reasoning": "<max 500 chars, MUST cite specific numbers from input data>",
    "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
    "risks": ["<risk1>", "<risk2>"],
    "entry_strategy": "MARKET" | "LIMIT_ON_DIP" | "SCALE_IN",
    "time_horizon_days": <int 5-20>
}

RULES:
- NEVER reference data not provided in the input
- If fundamental data is missing, fundamental_score MUST be 5.0
- If no news provided, sentiment_score MUST be 5.0
- reasoning MUST cite at least 2 specific numbers from input
- All text in English"""


class AIAnalyzer:
    """Google Gemini 기반 매수 추천 분석기"""

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
                system_instruction=SYSTEM_PROMPT,
                generation_config=genai.GenerationConfig(
                    temperature=settings.AI_TEMPERATURE,
                    max_output_tokens=settings.AI_MAX_TOKENS,
                    response_mime_type="application/json",
                ),
            )
            logger.debug(f"Gemini 모델 초기화 완료: {settings.GEMINI_MODEL}")
        except ImportError:
            raise RuntimeError(
                "google-generativeai 패키지가 설치되지 않았습니다. "
                "pip install google-generativeai 로 설치하세요."
            )
        return self._model

    def _build_analysis_context(self, ticker: str, db) -> dict:
        """DB에서 분석 컨텍스트 데이터를 수집합니다."""
        stock = db.query(Stock).filter(Stock.ticker == ticker).first()
        if stock is None:
            return {}

        # 최근 35일 일봉 데이터
        price_rows = (
            db.query(PriceHistory)
            .filter(
                PriceHistory.stock_id == stock.id,
                PriceHistory.interval == "1d",
            )
            .order_by(PriceHistory.timestamp.desc())
            .limit(35)
            .all()
        )
        price_rows = list(reversed(price_rows))

        prices = [
            {
                "date": r.timestamp.strftime("%Y-%m-%d"),
                "open": round(r.open, 2),
                "high": round(r.high, 2),
                "low": round(r.low, 2),
                "close": round(r.close, 2),
                "volume": r.volume,
            }
            for r in price_rows
        ]

        # 최신 기술적 지표 2개 (현재 + 전일, MACD 방향 전환 감지용) [E]
        ind_rows = (
            db.query(TechnicalIndicator)
            .filter(TechnicalIndicator.stock_id == stock.id)
            .order_by(TechnicalIndicator.date.desc())
            .limit(2)
            .all()
        )
        ind = ind_rows[0] if ind_rows else None
        prev_ind = ind_rows[1] if len(ind_rows) > 1 else None

        indicators = {}
        if ind:
            indicators = {
                "date": ind.date.strftime("%Y-%m-%d"),
                "rsi_14": round(ind.rsi_14, 2) if ind.rsi_14 else None,
                "macd": round(ind.macd, 4) if ind.macd else None,
                "macd_signal": round(ind.macd_signal, 4) if ind.macd_signal else None,
                "macd_hist": round(ind.macd_hist, 4) if ind.macd_hist else None,
                "bb_upper": round(ind.bb_upper, 2) if ind.bb_upper else None,
                "bb_middle": round(ind.bb_middle, 2) if ind.bb_middle else None,
                "bb_lower": round(ind.bb_lower, 2) if ind.bb_lower else None,
                "ma_20": round(ind.ma_20, 2) if ind.ma_20 else None,
                "ma_50": round(ind.ma_50, 2) if ind.ma_50 else None,
                "ma_200": round(ind.ma_200, 2) if ind.ma_200 else None,
                "volume_ma_20": round(ind.volume_ma_20, 0) if ind.volume_ma_20 else None,
                "adx_14": round(ind.adx_14, 2) if ind.adx_14 else None,
                "atr_14": round(ind.atr_14, 2) if ind.atr_14 else None,
            }
            # MACD 방향 전환 감지 [E]
            macd_crossover = None
            if ind.macd_hist is not None and prev_ind and prev_ind.macd_hist is not None:
                if prev_ind.macd_hist <= 0 and ind.macd_hist > 0:
                    macd_crossover = "GOLDEN_CROSS"
                elif prev_ind.macd_hist >= 0 and ind.macd_hist < 0:
                    macd_crossover = "DEAD_CROSS"
            indicators["macd_crossover"] = macd_crossover
            indicators["prev_macd_hist"] = round(prev_ind.macd_hist, 4) if prev_ind and prev_ind.macd_hist else None

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
                "summary": n.summary or "",
                "sentiment": round(n.sentiment, 3) if n.sentiment else None,
                "published_at": n.published_at.strftime("%Y-%m-%d") if n.published_at else None,
            }
            for n in news_rows
        ]

        # 종목 기본 정보
        stock_info = {
            "ticker": stock.ticker,
            "name": stock.name,
            "sector": stock.sector,
            "industry": stock.industry,
            "market_cap": stock.market_cap,
            "exchange": stock.exchange,
            "short_ratio": stock.short_ratio,
            "short_pct_of_float": stock.short_pct_of_float,
        }

        # 기본 재무 데이터 (fundamental_score 할루시네이션 방지)
        fundamentals = {}
        try:
            import yfinance as yf
            yt = yf.Ticker(ticker)
            info = yt.info
            fundamentals = {
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "ps_ratio": info.get("priceToSalesTrailing12Months"),
                "dividend_yield": info.get("dividendYield"),
                "eps_trailing": info.get("trailingEps"),
                "eps_forward": info.get("forwardEps"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "roe": info.get("returnOnEquity"),
                "free_cash_flow": info.get("freeCashflow"),
                "held_pct_institutions": info.get("heldPercentInstitutions"),
                "held_pct_insiders": info.get("heldPercentInsiders"),
            }
        except Exception as e:
            logger.debug(f"[{ticker}] 재무 데이터 조회 실패 (무시): {e}")

        # 백테스팅 과거 성과 (lazy import, 순환 임포트 방지) [C]
        past_performance = {}
        try:
            from analysis.backtester import backtester as _backtester
            accuracy = _backtester.get_accuracy_stats(days=90)
            breakdown = _backtester.get_action_breakdown(days=90)
            past_performance = {
                "overall": {
                    "total": accuracy.get("total_recommendations"),
                    "with_outcomes": accuracy.get("with_outcomes"),
                    "win_rate": accuracy.get("win_rate"),
                    "avg_return": accuracy.get("avg_return"),
                    "sharpe_proxy": accuracy.get("sharpe_proxy"),
                },
                "by_action": breakdown,
            }
        except Exception as e:
            logger.debug(f"[{ticker}] 과거 성과 조회 실패 (무시): {e}")

        # 시장 국면 데이터 (SPY, QQQ, ^VIX) [G]
        market_context = {}
        try:
            from data_fetcher.market_data import market_fetcher as _mf
            for symbol in ["SPY", "QQQ", "^VIX", "^TNX"]:
                data = _mf.fetch_realtime_price(symbol)
                if data:
                    market_context[symbol] = {
                        "price": data["price"],
                        "change_pct": data["change_pct"],
                    }
        except Exception as e:
            logger.debug(f"[{ticker}] 시장 국면 데이터 조회 실패 (무시): {e}")

        # 실적발표일 조회 [K]
        earnings_warning = None
        try:
            import yfinance as yf
            yt = yf.Ticker(ticker)
            ed = getattr(yt.fast_info, "earnings_date", None)
            if ed is None:
                cal = yt.calendar
                if cal is not None and "Earnings Date" in cal:
                    ed_list = cal["Earnings Date"]
                    if ed_list:
                        ed = ed_list[0] if hasattr(ed_list, "__iter__") else ed_list
            if ed is not None:
                if hasattr(ed, "tzinfo") and ed.tzinfo:
                    ed = ed.replace(tzinfo=None)
                days_until = (ed - datetime.now()).days
                if 0 <= days_until <= 7:
                    earnings_warning = f"⚠️ EARNINGS IN {days_until} DAYS ({ed.strftime('%Y-%m-%d')})"
                elif days_until > 7:
                    earnings_warning = f"다음 실적발표: {ed.strftime('%Y-%m-%d')} ({days_until}일 후)"
        except Exception:
            pass

        return {
            "stock": stock_info,
            "prices": prices,
            "indicators": indicators,
            "news": news,
            "current_price": prices[-1]["close"] if prices else None,
            "fundamentals": fundamentals,
            "past_performance": past_performance,
            "market_context": market_context,
            "earnings_warning": earnings_warning,
        }

    def _build_prompt(self, context: dict) -> str:
        """Pre-compute derived metrics and present as narrative summary."""
        stock = context.get("stock", {})
        prices = context.get("prices", [])
        ind = context.get("indicators", {})
        news = context.get("news", [])
        current_price = context.get("current_price")
        fundamentals = context.get("fundamentals", {})

        prompt_parts = [
            f"## {stock.get('ticker')} — {stock.get('name')}",
            f"Sector: {stock.get('sector')} | Industry: {stock.get('industry')}",
            f"Market Cap: ${stock.get('market_cap', 0):,.0f}" if stock.get("market_cap") else "Market Cap: N/A",
            f"Current Price: ${current_price:.2f}" if current_price else "",
            f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M')} ET",
            "",
        ]

        # === PRICE ACTION SUMMARY ===
        if prices and len(prices) >= 5:
            latest = prices[-1]
            p5 = prices[-5] if len(prices) >= 5 else prices[0]
            p10 = prices[-10] if len(prices) >= 10 else prices[0]
            p20 = prices[-20] if len(prices) >= 20 else prices[0]

            ret_5d = ((latest["close"] - p5["close"]) / p5["close"]) * 100 if p5["close"] else 0
            ret_10d = ((latest["close"] - p10["close"]) / p10["close"]) * 100 if p10["close"] else 0
            ret_20d = ((latest["close"] - p20["close"]) / p20["close"]) * 100 if p20["close"] else 0

            high_35d = max(p["high"] for p in prices)
            low_35d = min(p["low"] for p in prices)
            pct_from_high = ((latest["close"] - high_35d) / high_35d) * 100 if high_35d else 0
            pct_from_low = ((latest["close"] - low_35d) / low_35d) * 100 if low_35d else 0

            recent_5d_vol = sum(p["volume"] for p in prices[-5:]) / 5
            prior_5d_vol = sum(p["volume"] for p in prices[-10:-5]) / 5 if len(prices) >= 10 else recent_5d_vol
            vol_change = ((recent_5d_vol - prior_5d_vol) / prior_5d_vol * 100) if prior_5d_vol > 0 else 0

            last3 = prices[-3:]
            candle_desc = []
            for p in last3:
                direction = "+" if p["close"] >= p["open"] else "-"
                body_pct = abs(p["close"] - p["open"]) / p["open"] * 100 if p["open"] else 0
                candle_desc.append(f"{p['date']}: {direction}{body_pct:.1f}% C:{p['close']:.2f} V:{p['volume']:,}")

            prompt_parts.extend([
                "## Price Action:",
                f"- Returns: 5d={ret_5d:+.2f}% | 10d={ret_10d:+.2f}% | 20d={ret_20d:+.2f}%",
                f"- 35d range: High=${high_35d:.2f} ({pct_from_high:+.1f}%) | Low=${low_35d:.2f} ({pct_from_low:+.1f}%)",
                f"- Volume trend: 5d avg={recent_5d_vol:,.0f} ({vol_change:+.1f}% vs prior 5d)",
                "- Last 3 sessions: " + " | ".join(candle_desc),
                "",
            ])

        # === TECHNICAL INDICATORS ===
        if ind:
            rsi = ind.get("rsi_14")
            macd_hist = ind.get("macd_hist")
            macd_crossover = ind.get("macd_crossover")
            prev_macd_hist = ind.get("prev_macd_hist")
            adx = ind.get("adx_14")
            atr = ind.get("atr_14")
            bb_upper = ind.get("bb_upper")
            bb_lower = ind.get("bb_lower")
            bb_middle = ind.get("bb_middle")
            ma_20 = ind.get("ma_20")
            ma_50 = ind.get("ma_50")
            ma_200 = ind.get("ma_200")
            vol_ma_20 = ind.get("volume_ma_20")

            tech_lines = [f"## Technical Indicators ({ind.get('date', 'N/A')}):"]

            if rsi is not None:
                rsi_label = "OVERSOLD" if rsi < 30 else ("OVERBOUGHT" if rsi > 70 else "NEUTRAL")
                tech_lines.append(f"- RSI(14): {rsi:.1f} [{rsi_label}]")

            if macd_hist is not None:
                direction = ""
                if macd_crossover == "GOLDEN_CROSS":
                    direction = " ** CROSSED POSITIVE **"
                elif macd_crossover == "DEAD_CROSS":
                    direction = " ** CROSSED NEGATIVE **"
                elif prev_macd_hist is not None:
                    direction = " (improving)" if macd_hist > prev_macd_hist else " (deteriorating)"
                tech_lines.append(f"- MACD Hist: {macd_hist:.4f}{direction}")

            if current_price and bb_upper and bb_lower and (bb_upper - bb_lower) > 0:
                bb_pct = (current_price - bb_lower) / (bb_upper - bb_lower) * 100
                bb_label = "UPPER ZONE" if bb_pct > 80 else ("LOWER ZONE" if bb_pct < 20 else "MIDDLE")
                tech_lines.append(f"- BB Position: {bb_pct:.1f}% [{bb_label}] (L:${bb_lower:.2f} M:${bb_middle:.2f} U:${bb_upper:.2f})")

            ma_parts = []
            if current_price and ma_20:
                ma_parts.append(f"MA20:${ma_20:.2f}({(current_price-ma_20)/ma_20*100:+.1f}%)")
            if current_price and ma_50:
                ma_parts.append(f"MA50:${ma_50:.2f}({(current_price-ma_50)/ma_50*100:+.1f}%)")
            if current_price and ma_200:
                ma_parts.append(f"MA200:${ma_200:.2f}({(current_price-ma_200)/ma_200*100:+.1f}%)")
            if ma_parts:
                alignment = "BULLISH" if (ma_20 and ma_50 and ma_200 and ma_20 > ma_50 > ma_200) else \
                            "BEARISH" if (ma_20 and ma_50 and ma_200 and ma_20 < ma_50 < ma_200) else "MIXED"
                tech_lines.append(f"- MAs [{alignment}]: " + " | ".join(ma_parts))

            if adx is not None:
                adx_label = "STRONG TREND" if adx > 25 else ("DEVELOPING" if adx > 20 else "RANGE-BOUND")
                tech_lines.append(f"- ADX(14): {adx:.1f} [{adx_label}]")

            if atr is not None and current_price:
                tech_lines.append(f"- ATR(14): ${atr:.2f} ({atr/current_price*100:.2f}% daily volatility)")

            if vol_ma_20 and prices:
                latest_vol = prices[-1]["volume"]
                vol_ratio = latest_vol / vol_ma_20 if vol_ma_20 > 0 else 1
                vol_label = "ABOVE AVG" if vol_ratio > 1.2 else ("BELOW AVG" if vol_ratio < 0.8 else "NORMAL")
                tech_lines.append(f"- Volume: {latest_vol:,.0f} vs 20d-MA:{vol_ma_20:,.0f} ({vol_ratio:.2f}x [{vol_label}])")

            prompt_parts.extend(tech_lines + [""])

        # === FUNDAMENTALS (compact) ===
        if fundamentals:
            fund_items = []
            pe = fundamentals.get("pe_ratio")
            if pe is not None:
                fund_items.append(f"P/E:{pe:.1f}")
            fwd_pe = fundamentals.get("forward_pe")
            if fwd_pe is not None:
                fund_items.append(f"FwdPE:{fwd_pe:.1f}")
            for key, label in [("pb_ratio","P/B"),("eps_trailing","EPS"),("debt_to_equity","D/E")]:
                val = fundamentals.get(key)
                if val is not None:
                    fund_items.append(f"{label}:{val:.2f}")
            for key, label in [("revenue_growth","RevGr"),("profit_margin","Margin"),("roe","ROE"),("dividend_yield","DivY")]:
                val = fundamentals.get(key)
                if val is not None and isinstance(val, (int, float)):
                    fund_items.append(f"{label}:{val:.1%}")
            fcf = fundamentals.get("free_cash_flow")
            if fcf is not None and isinstance(fcf, (int, float)):
                fund_items.append(f"FCF:${fcf:,.0f}")

            if fund_items:
                prompt_parts.extend([f"## Fundamentals: " + " | ".join(fund_items), ""])
            else:
                prompt_parts.extend(["## Fundamentals: No data (score as 5.0)", ""])

        # === OWNERSHIP ===
        ownership_items = []
        sr = stock.get("short_ratio")
        sp = stock.get("short_pct_of_float")
        ip = fundamentals.get("held_pct_institutions")
        inp = fundamentals.get("held_pct_insiders")
        if sr is not None:
            ownership_items.append(f"ShortRatio:{sr:.1f}d")
        if sp is not None:
            ownership_items.append(f"ShortFloat:{sp:.1%}")
        if ip is not None:
            ownership_items.append(f"Inst:{ip:.1%}")
        if inp is not None:
            ownership_items.append(f"Insider:{inp:.1%}")
        if ownership_items:
            prompt_parts.extend([f"## Ownership: " + " | ".join(ownership_items), ""])

        # === MARKET CONTEXT ===
        market_ctx = context.get("market_context", {})
        if market_ctx:
            items = []
            spy = market_ctx.get("SPY")
            qqq = market_ctx.get("QQQ")
            vix = market_ctx.get("^VIX")
            tnx = market_ctx.get("^TNX")
            if spy: items.append(f"SPY:{spy['change_pct']:+.2f}%")
            if qqq: items.append(f"QQQ:{qqq['change_pct']:+.2f}%")
            if vix:
                vl = "FEAR" if vix["price"]>30 else ("CAUTION" if vix["price"]>20 else "CALM")
                items.append(f"VIX:{vix['price']:.1f}[{vl}]")
            if tnx: items.append(f"10Y:{tnx['price']:.2f}%")
            regime = "RISK-OFF" if (vix and vix["price"]>25) else \
                     "BULLISH" if (spy and spy["change_pct"]>0.5) else \
                     "BEARISH" if (spy and spy["change_pct"]<-0.5) else "NEUTRAL"
            prompt_parts.extend([f"## Market [{regime}]: " + " | ".join(items), ""])

        # === EARNINGS ===
        ew = context.get("earnings_warning")
        if ew:
            prompt_parts.extend([f"## EARNINGS ALERT: {ew}", ""])

        # === AI TRACK RECORD ===
        pp = context.get("past_performance", {})
        ov = pp.get("overall", {})
        if ov.get("with_outcomes", 0) > 0:
            parts = [f"Evaluated:{ov['with_outcomes']}"]
            if ov.get("win_rate") is not None: parts.append(f"WinRate:{ov['win_rate']:.0f}%")
            if ov.get("avg_return") is not None: parts.append(f"AvgRet:{ov['avg_return']:.1f}%")
            prompt_parts.extend([f"## AI Track Record (90d): " + " | ".join(parts), ""])

        # === NEWS ===
        if news:
            news_lines = ["## News:"]
            for n in news:
                sent = n.get("sentiment")
                sl = " [+]" if sent and sent > 0.3 else (" [-]" if sent and sent < -0.3 else "")
                title = n.get("title", "")
                news_lines.append(f"- [{n.get('published_at','N/A')}]{sl} {title}")
            prompt_parts.extend(news_lines + [""])
        else:
            prompt_parts.extend(["## News: None (sentiment_score should be 5.0)", ""])

        prompt_parts.append("Analyze all data. Follow the decision framework. Compute weighted_score, then derive action. JSON only.")
        return "\n".join(prompt_parts)

    def _parse_response(self, text: str, current_price: float | None = None) -> dict:
        """AI 응답을 파싱하고 필수 필드를 검증합니다."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # JSON 블록 추출 시도
            import re
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"JSON 파싱 실패: {text[:200]}")

        required_fields = ["action", "confidence", "reasoning"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"필수 필드 누락: {field}")

        valid_actions = {"STRONG_BUY", "BUY", "HOLD"}
        if data["action"] not in valid_actions:
            raise ValueError(f"유효하지 않은 action: {data['action']}")

        confidence = float(data["confidence"])
        if not (0.0 <= confidence <= 1.0):
            confidence = max(0.0, min(1.0, confidence))
        data["confidence"] = confidence

        # 기본값 설정
        data.setdefault("target_price", None)
        data.setdefault("stop_loss", None)
        data.setdefault("technical_score", None)
        data.setdefault("fundamental_score", None)
        data.setdefault("sentiment_score", None)
        data.setdefault("key_factors", [])
        data.setdefault("risks", [])
        data.setdefault("weighted_score", None)
        data.setdefault("entry_strategy", "MARKET")
        data.setdefault("time_horizon_days", 14)

        # weighted_score 일관성 검증
        ws = data.get("weighted_score")
        ts = data.get("technical_score")
        fs = data.get("fundamental_score")
        ss = data.get("sentiment_score")
        if ws is not None and ts is not None and fs is not None and ss is not None:
            expected_ws = ts * 0.45 + fs * 0.30 + ss * 0.25
            if abs(ws - expected_ws) > 1.5:
                logger.warning(f"weighted_score 불일치: {ws:.1f} vs 예상 {expected_ws:.1f}")
                data["weighted_score"] = round(expected_ws, 2)

        # target_price / stop_loss 합리성 검증
        if current_price is not None and current_price > 0:
            tp = data.get("target_price")
            sl = data.get("stop_loss")
            if tp is not None:
                if not (current_price * 0.95 <= tp <= current_price * 1.30):
                    logger.warning(
                        f"target_price ${tp} 범위 초과 (현재가 ${current_price}의 0.95~1.30배) → None"
                    )
                    data["target_price"] = None
            if sl is not None:
                if not (current_price * 0.85 <= sl <= current_price * 0.99):
                    logger.warning(
                        f"stop_loss ${sl} 범위 초과 (현재가 ${current_price}의 0.85~0.99배) → None"
                    )
                    data["stop_loss"] = None

        # score 필드 범위 검증 (0.0~10.0 클램핑)
        for score_field in ["technical_score", "fundamental_score", "sentiment_score"]:
            val = data.get(score_field)
            if val is not None:
                data[score_field] = max(0.0, min(10.0, float(val)))

        return data

    def analyze_ticker(self, ticker: str) -> AIRecommendation | None:
        """
        단일 종목을 분석하고 AIRecommendation을 DB에 저장합니다.

        Returns:
            AIRecommendation 객체 또는 None (실패 시)
        """
        logger.info(f"[AI 분석] {ticker} 매수 분석 시작")

        try:
            model = self._get_model()
        except RuntimeError as e:
            logger.error(f"[AI 분석] 모델 초기화 실패: {e}")
            return None

        with get_db() as db:
            context = self._build_analysis_context(ticker, db)
            if not context or not context.get("prices"):
                logger.warning(f"[{ticker}] 분석 데이터 부족, 스킵")
                return None

            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                logger.error(f"[{ticker}] 종목 정보 없음")
                return None

            prompt = self._build_prompt(context)

            try:
                import time
                last_err = None
                for attempt in range(3):
                    try:
                        response = model.generate_content(prompt)
                        break
                    except Exception as api_err:
                        last_err = api_err
                        if attempt < 2:
                            wait_time = 5 * (2 ** attempt)  # 5s, 10s, 20s
                            logger.warning(
                                f"[{ticker}] API 호출 실패 (시도 {attempt + 1}/3), {wait_time}초 후 재시도: {api_err}"
                            )
                            time.sleep(wait_time)
                        else:
                            raise last_err
                parsed = self._parse_response(
                    response.text,
                    current_price=context.get("current_price"),
                )
            except Exception as e:
                logger.error(f"[{ticker}] AI API 호출 실패: {e}")
                return None

            # 1. VIX 신뢰도 감쇄 (극단적 공포 시에만 — 프롬프트가 이미 VIX 20-30 처리)
            vix_data = context.get("market_context", {}).get("^VIX")
            if vix_data:
                vix_level = vix_data.get("price")
                if vix_level is not None and vix_level > 30:
                    penalty = min(0.10, (vix_level - 30) / 100)
                    parsed["confidence"] = round(parsed["confidence"] * (1 - penalty), 2)

            # 2. 신뢰도 임계값 체크 (VIX 조정 후 최종 게이트)
            threshold = settings.BUY_CONFIDENCE_THRESHOLD
            if parsed["action"] in ("BUY", "STRONG_BUY") and parsed["confidence"] < threshold:
                logger.info(
                    f"[{ticker}] 신뢰도 {parsed['confidence']:.0%} < 임계값 {threshold:.0%} "
                    f"→ HOLD 다운그레이드 (원래: {parsed['action']})"
                )
                parsed["action"] = "HOLD"
                # confidence 유지 — 이미 낮은 값을 추가 감쇄하지 않음

            # 3. VIX 극단적 수준에서 STRONG_BUY 다운그레이드만
            if vix_data and isinstance(vix_data, dict):
                vix_level = vix_data.get("price")
                if vix_level is not None and vix_level > 35 and parsed["action"] == "STRONG_BUY":
                    parsed["action"] = "BUY"
                    logger.info(f"[{ticker}] VIX {vix_level:.1f} > 35 → BUY 다운그레이드")

            # 신뢰도 보정: 과거 성과가 좋을 때만 상향 (하향 감쇄 금지)
            try:
                from analysis.backtester import backtester as _bt
                breakdown = _bt.get_action_breakdown(days=90)
                action_stats = {b["action"]: b for b in breakdown}
                if parsed["action"] in action_stats:
                    hist_win_rate = action_stats[parsed["action"]]["win_rate"] / 100.0
                    if hist_win_rate > parsed["confidence"]:
                        calibrated = 0.85 * parsed["confidence"] + 0.15 * hist_win_rate
                        parsed["confidence"] = round(calibrated, 2)
            except Exception:
                pass

            # 리스크 매니저 연동: BUY/STRONG_BUY인 경우 리스크 체크
            if parsed["action"] in ("BUY", "STRONG_BUY"):
                try:
                    from analysis.risk_manager import risk_manager
                    sector = stock.sector if stock else None
                    risk_check = risk_manager.check_can_buy(ticker, sector)
                    if not risk_check["allowed"]:
                        logger.info(
                            f"[{ticker}] 리스크 체크 실패: {risk_check['reason']} "
                            f"→ HOLD 다운그레이드 (원래: {parsed['action']})"
                        )
                        parsed["reasoning"] += f" [리스크 관리: {risk_check['reason']}]"
                        parsed["action"] = "HOLD"
                except Exception as risk_err:
                    logger.debug(f"[{ticker}] 리스크 체크 실패 (무시): {risk_err}")

            # DB 저장
            rec = AIRecommendation(
                stock_id=stock.id,
                recommendation_date=datetime.now(timezone.utc).replace(tzinfo=None),
                action=parsed["action"],
                confidence=parsed["confidence"],
                target_price=parsed.get("target_price"),
                stop_loss=parsed.get("stop_loss"),
                reasoning=parsed["reasoning"],
                technical_score=parsed.get("technical_score"),
                fundamental_score=parsed.get("fundamental_score"),
                sentiment_score=parsed.get("sentiment_score"),
                price_at_recommendation=context.get("current_price"),
            )
            db.add(rec)
            db.flush()

            action_emoji = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "HOLD": "🟡"}.get(parsed["action"], "")
            logger.success(
                f"[AI 분석] {ticker} {action_emoji} {parsed['action']} "
                f"(신뢰도: {parsed['confidence']:.0%})"
            )
            logger.debug(f"[{ticker}] 근거: {parsed['reasoning'][:100]}...")
            return rec

    def get_priority_tickers(self, max_count: int = 50) -> list[str]:
        """
        Multi-factor scoring: dual sub-model (momentum + mean-reversion)
        with market regime-adaptive blending.

        Scans all 818 tickers using DB-cached indicators (no API calls).
        Selects top max_count for AI analysis.
        """
        from database.models import TechnicalIndicator, PriceHistory
        from datetime import timedelta
        from config.tickers import ALL_TICKERS

        watchlist = ALL_TICKERS
        scores: dict[str, float] = {}

        cutoff_date = datetime.now() - timedelta(days=5)  # 주말+공휴일 대비

        # ── STEP 0: Market Regime Detection ──
        regime_mom_w = 0.65  # default: 65% momentum, 35% reversion
        regime_rev_w = 0.35
        regime_name = "trending"

        try:
            from data_fetcher.market_data import market_fetcher as _mf
            vix_data = _mf.fetch_realtime_price("^VIX")
            vix_level = vix_data["price"] if vix_data else 18.0

            if vix_level > 28:
                regime_name = "high_volatility"
                regime_mom_w, regime_rev_w = 0.25, 0.75
            elif vix_level > 20:
                regime_name = "transitional"
                regime_mom_w, regime_rev_w = 0.45, 0.55
            else:
                regime_name = "trending"
                regime_mom_w, regime_rev_w = 0.70, 0.30

            logger.debug(f"[Scoring] Regime={regime_name} VIX={vix_level:.1f} mom={regime_mom_w:.0%} rev={regime_rev_w:.0%}")
        except Exception as e:
            logger.debug(f"[Scoring] Regime detection failed: {e}")

        # ── STEP 1-5: Per-stock scoring ──
        with get_db() as db:
            for ticker in watchlist:
                stock = db.query(Stock).filter(Stock.ticker == ticker).first()
                if stock is None:
                    continue

                ind = (
                    db.query(TechnicalIndicator)
                    .filter(
                        TechnicalIndicator.stock_id == stock.id,
                        TechnicalIndicator.date >= cutoff_date,
                    )
                    .order_by(TechnicalIndicator.date.desc())
                    .first()
                )
                if ind is None:
                    continue

                prev_ind = (
                    db.query(TechnicalIndicator)
                    .filter(
                        TechnicalIndicator.stock_id == stock.id,
                        TechnicalIndicator.date < ind.date,
                    )
                    .order_by(TechnicalIndicator.date.desc())
                    .first()
                )

                price_rows = (
                    db.query(PriceHistory)
                    .filter(
                        PriceHistory.stock_id == stock.id,
                        PriceHistory.interval == "1d",
                    )
                    .order_by(PriceHistory.timestamp.desc())
                    .limit(6)
                    .all()
                )
                if not price_rows:
                    continue

                current_price = price_rows[0].close
                latest_volume = price_rows[0].volume

                # ── MOMENTUM SUB-SCORE ──
                momentum = 0.0

                # M1: MA Alignment (0-4)
                ma_count = 0
                if current_price and ind.ma_20 and current_price > ind.ma_20: ma_count += 1
                if current_price and ind.ma_50 and current_price > ind.ma_50: ma_count += 1
                if current_price and ind.ma_200 and current_price > ind.ma_200: ma_count += 1
                if ind.ma_20 and ind.ma_50 and ind.ma_200 and ind.ma_20 > ind.ma_50 > ind.ma_200:
                    ma_count += 1  # Perfect stacking bonus
                momentum += min(ma_count, 4)

                # M2: MACD (0-3)
                is_golden_cross = False
                macd_pts = 0.0
                if ind.macd_hist is not None:
                    if (prev_ind and prev_ind.macd_hist is not None
                            and prev_ind.macd_hist <= 0 and ind.macd_hist > 0):
                        is_golden_cross = True
                        macd_pts = 2.5
                    elif ind.macd_hist > 0:
                        macd_pts = 1.5
                        if prev_ind and prev_ind.macd_hist is not None and ind.macd_hist > prev_ind.macd_hist:
                            macd_pts = 2.0  # Accelerating
                momentum += min(macd_pts, 3.0)

                # M3: ADX multiplier
                adx_mult = 1.0
                if ind.adx_14 is not None:
                    if ind.adx_14 > 30: adx_mult = 1.3
                    elif ind.adx_14 > 25: adx_mult = 1.15
                    elif ind.adx_14 < 20: adx_mult = 0.7
                momentum *= adx_mult

                # M4: RSI Momentum Zone (50-65 in uptrend)
                if ind.rsi_14 is not None and 50 <= ind.rsi_14 <= 65:
                    momentum += 1.5

                # ── MEAN-REVERSION SUB-SCORE ──
                reversion = 0.0

                # R1: RSI Oversold (0-3)
                if ind.rsi_14 is not None:
                    if ind.rsi_14 < 25: reversion += 3.0
                    elif ind.rsi_14 < 30: reversion += 2.5
                    elif ind.rsi_14 < 35: reversion += 1.5
                    elif ind.rsi_14 < 40: reversion += 0.5

                # R2: StochRSI oversold cross (0-2)
                if ind.stoch_rsi_k is not None and ind.stoch_rsi_d is not None:
                    if ind.stoch_rsi_k < 0.20 and ind.stoch_rsi_d < 0.20:
                        reversion += 1.0
                        if (prev_ind and prev_ind.stoch_rsi_k is not None
                                and prev_ind.stoch_rsi_d is not None
                                and prev_ind.stoch_rsi_k <= prev_ind.stoch_rsi_d
                                and ind.stoch_rsi_k > ind.stoch_rsi_d):
                            reversion += 1.0  # Bullish cross in oversold

                # R3: BB Position (0-2.5)
                if (current_price and ind.bb_upper and ind.bb_lower
                        and (ind.bb_upper - ind.bb_lower) > 0):
                    bb_pct = (current_price - ind.bb_lower) / (ind.bb_upper - ind.bb_lower) * 100
                    if bb_pct < 10: reversion += 2.5
                    elif bb_pct < 20: reversion += 2.0
                    elif bb_pct < 30: reversion += 1.0

                # R4: BB Squeeze (0-1.5)
                if (ind.bb_upper and ind.bb_lower and ind.bb_middle and ind.bb_middle > 0
                        and prev_ind and prev_ind.bb_upper and prev_ind.bb_lower
                        and prev_ind.bb_middle and prev_ind.bb_middle > 0):
                    bb_width = (ind.bb_upper - ind.bb_lower) / ind.bb_middle
                    prev_width = (prev_ind.bb_upper - prev_ind.bb_lower) / prev_ind.bb_middle
                    if bb_width < 0.04 and bb_width < prev_width:
                        reversion += 1.5
                    elif bb_width < 0.06:
                        reversion += 0.5

                # ── VOLUME MULTIPLIER ──
                vol_mult = 1.0
                if latest_volume and ind.volume_ma_20 and ind.volume_ma_20 > 0:
                    vr = latest_volume / ind.volume_ma_20
                    if vr > 2.0: vol_mult = 1.4
                    elif vr > 1.3: vol_mult = 1.2
                    elif vr < 0.5: vol_mult = 0.6
                    elif vr < 0.8: vol_mult = 0.8

                # ── OBV DIVERGENCE BONUS ──
                obv_bonus = 0.0
                if ind.obv is not None and prev_ind and prev_ind.obv is not None:
                    obv_chg = ind.obv - prev_ind.obv
                    price_chg = price_rows[0].close - price_rows[1].close if len(price_rows) >= 2 else 0
                    if obv_chg > 0 and price_chg <= 0:
                        obv_bonus = 1.5  # Bullish divergence
                    elif obv_chg > 0 and price_chg > 0:
                        obv_bonus = 0.5

                # ── PENALTIES ──

                # P1: Falling knife
                knife_pen = 0.0
                if len(price_rows) >= 4:
                    down_days = 0
                    for i in range(min(len(price_rows) - 1, 4)):
                        if price_rows[i].close < price_rows[i + 1].close:
                            down_days += 1
                        else:
                            break
                    if down_days >= 4: knife_pen = 0.4
                    elif down_days >= 3: knife_pen = 0.25

                # Below MA200 = reduce reversion score
                if current_price and ind.ma_200 and current_price < ind.ma_200:
                    reversion *= 0.5

                # P2: Bull trap for golden cross
                if is_golden_cross:
                    trap = 0.0
                    if latest_volume and ind.volume_ma_20 and latest_volume < ind.volume_ma_20 * 0.8:
                        trap += 0.2
                    if (current_price and ind.ma_20 and ind.ma_50
                            and current_price < ind.ma_20 and current_price < ind.ma_50):
                        trap += 0.3
                    if trap > 0:
                        momentum -= macd_pts * min(trap, 0.5)
                        momentum = max(momentum, 0)

                # P3: Overbought guard
                if ind.rsi_14 is not None and ind.rsi_14 > 75:
                    momentum *= 0.3
                    reversion = 0

                # ── FINAL SCORE ──
                raw = regime_mom_w * momentum + regime_rev_w * reversion
                adjusted = raw * vol_mult + obv_bonus
                final = adjusted * (1.0 - knife_pen)
                final = max(final, 0.0)

                if final > 0.5:
                    scores[ticker] = round(final, 2)

        sorted_tickers = sorted(scores, key=lambda t: scores[t], reverse=True)
        selected = sorted_tickers[:max_count]

        logger.info(
            f"[AI Priority] Regime={regime_name} | Scanned {len(watchlist)}, "
            f"scored {len(scores)}, selected top {len(selected)}"
        )
        if selected:
            top5 = [(t, f"{scores[t]:.2f}") for t in selected[:5]]
            logger.debug(f"[AI Priority] Top 5: {top5}")

        return selected

    def analyze_all_watchlist(self) -> dict[str, str]:
        """
        watchlist 전체를 기술적 필터링 후 상위 50개 종목을 AI 분석합니다.
        무료 티어 API 제한(RPM 15) 우회를 위해 5초의 대기 시간을 갖고, 
        429 Quota 에러 시 60초 대기 후 재시도하는 로직(Backoff)을 포함합니다.

        Returns:
            {ticker: action} 딕셔너리
        """
        results = {}
        # 매수 분석은 전체 유니버스(ALL_TICKERS)에서 후보를 찾음
        from config.tickers import ALL_TICKERS
        all_tickers = ALL_TICKERS

        # 50개 초과 시 우선순위 필터 적용 (이 이상은 현실적으로 너무 오래 걸림)
        if len(all_tickers) > 50:
            tickers = self.get_priority_tickers(max_count=50)
            if not tickers:
                logger.warning("[AI 분석] 기술적 조건 충족 종목 없음. 전체 중 앞 50개로 대체.")
                tickers = all_tickers[:50]
            logger.info(f"[AI 분석] 우선순위 필터 적용: {len(all_tickers)}개 → {len(tickers)}개")
        else:
            tickers = all_tickers
            logger.info(f"[AI 분석] 전체 종목 분석 시작: {tickers}")

        import time
        from google.api_core.exceptions import ResourceExhausted

        for i, ticker in enumerate(tickers):
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"[AI 분석] ({i+1}/{len(tickers)}) {ticker} 시도 중...")
                    rec = self.analyze_ticker(ticker)
                    results[ticker] = rec.action if rec else "ERROR"
                    break # 성공 시 재시도 루프 탈출

                except ResourceExhausted as e:
                    # 429 오류 명시적 캡처 (Quota Exceeded)
                    if attempt < max_retries - 1:
                        logger.warning(f"[{ticker}] API 할당량 초과(429). 60초 대기 후 재시도... ({attempt+1}/{max_retries})")
                        time.sleep(60) # 60초 대기하며 쿼터 리셋 기다림
                    else:
                        logger.error(f"[{ticker}] 최대 재시도(3회) 실패(429 Error). 다음 종목으로 넘어갑니다: {e}")
                        results[ticker] = "ERROR"

                except Exception as e:
                    # 기타 치명적 에러 시 재시도하지 않고 넘어감
                    if '429' in str(e):
                        if attempt < max_retries - 1:
                            logger.warning(f"[{ticker}] API 할당량 초과(429 str). 60초 대기 후 재시도... ({attempt+1}/{max_retries})")
                            time.sleep(60)
                        else:
                            logger.error(f"[{ticker}] 최대 재시도 실패(429 Error): {e}")
                            results[ticker] = "ERROR"
                    else:
                        logger.error(f"[{ticker}] 분석 중 예외 발생: {e}")
                        results[ticker] = "ERROR"
                        break

            # Rate limit: 평상시 호출 딜레이 (분당 최대 13건 이하 통제)
            if i < len(tickers) - 1:
                time.sleep(4.5)

        buy_count = sum(1 for a in results.values() if a in ("BUY", "STRONG_BUY"))
        logger.info(f"[AI 분석] 구동 완료 — 매수 추천: {buy_count}/{len(tickers)}개 분석 완료")
        return results

    def get_todays_recommendations(self) -> list[dict]:
        """
        오늘 생성된 매수 추천 목록을 반환합니다 (대시보드용).
        """
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        with get_db() as db:
            recs = (
                db.query(AIRecommendation)
                .filter(AIRecommendation.recommendation_date >= today_start)
                .order_by(AIRecommendation.confidence.desc())
                .all()
            )

            results = []
            for r in recs:
                stock = db.query(Stock).filter(Stock.id == r.stock_id).first()
                results.append({
                    "ticker": stock.ticker if stock else "?",
                    "name": stock.name if stock else "?",
                    "action": r.action,
                    "confidence": r.confidence,
                    "target_price": r.target_price,
                    "stop_loss": r.stop_loss,
                    "reasoning": r.reasoning,
                    "technical_score": r.technical_score,
                    "fundamental_score": r.fundamental_score,
                    "sentiment_score": r.sentiment_score,
                    "price_at_recommendation": r.price_at_recommendation,
                    "recommendation_date": r.recommendation_date.strftime("%Y-%m-%d %H:%M"),
                })

        return results

    def get_recommendation_history(self, days: int = 30) -> list[dict]:
        """
        최근 N일간의 추천 이력을 반환합니다 (대시보드 이력/정확도용).
        """
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)

        with get_db() as db:
            recs = (
                db.query(AIRecommendation)
                .filter(AIRecommendation.recommendation_date >= cutoff)
                .order_by(AIRecommendation.recommendation_date.desc())
                .all()
            )

            results = []
            for r in recs:
                stock = db.query(Stock).filter(Stock.id == r.stock_id).first()
                results.append({
                    "ticker": stock.ticker if stock else "?",
                    "name": stock.name if stock else "?",
                    "action": r.action,
                    "confidence": r.confidence,
                    "price_at_recommendation": r.price_at_recommendation,
                    "target_price": r.target_price,
                    "stop_loss": r.stop_loss,
                    "reasoning": r.reasoning,
                    "is_executed": r.is_executed,
                    "outcome_return": r.outcome_return,
                    "recommendation_date": r.recommendation_date.strftime("%Y-%m-%d %H:%M"),
                })

        return results


# 싱글톤 인스턴스
ai_analyzer = AIAnalyzer()
