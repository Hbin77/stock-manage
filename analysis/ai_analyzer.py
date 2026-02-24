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
- STRONG_BUY: weighted_score >= 6.5 AND technical_score >= 6.0 AND confidence >= 0.70
- BUY: weighted_score >= 5.0 AND technical_score >= 4.0 AND confidence >= 0.50
- HOLD: below BUY thresholds
IMPORTANT: If technical_score >= 6 but you output HOLD, you MUST explain why in reasoning.
IMPORTANT: These are pre-filtered stocks (top 50 from 800+ universe). Expect 15-30% to be BUY candidates. Do NOT default to HOLD — evaluate objectively.

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
            logger.debug(f"Gemini 클라이언트 초기화 완료: {settings.GEMINI_MODEL}")
        except ImportError:
            raise RuntimeError(
                "google-genai 패키지가 설치되지 않았습니다. "
                "pip install google-genai 로 설치하세요."
            )
        return self._client

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
            client = self._get_client()
        except RuntimeError as e:
            logger.error(f"[AI 분석] 클라이언트 초기화 실패: {e}")
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
                import re as _re
                from google.genai import types
                last_err = None
                for attempt in range(3):
                    try:
                        response = client.models.generate_content(
                            model=settings.GEMINI_MODEL,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_PROMPT,
                                temperature=settings.AI_TEMPERATURE,
                                max_output_tokens=settings.AI_MAX_TOKENS,
                                thinking_config=types.ThinkingConfig(thinking_budget=1024),
                                response_mime_type="application/json",
                            ),
                        )
                        # 디버그: 응답 완성 여부 확인
                        finish = response.candidates[0].finish_reason if response.candidates else "NO_CANDIDATES"
                        logger.debug(f"[{ticker}] finish_reason={finish}, text_len={len(response.text) if response.text else 0}")
                        break
                    except Exception as api_err:
                        last_err = api_err
                        if attempt < 2:
                            wait_time = settings.GEMINI_BACKOFF_BASE * (2 ** attempt)
                            retry_match = _re.search(r"retry.*?(\d+)\.?\d*s", str(api_err), _re.IGNORECASE)
                            if retry_match:
                                wait_time = max(wait_time, int(retry_match.group(1)) + 1)
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

            # 신뢰도 임계값 체크 (최종 게이트)
            threshold = settings.BUY_CONFIDENCE_THRESHOLD
            if parsed["action"] in ("BUY", "STRONG_BUY") and parsed["confidence"] < threshold:
                logger.info(
                    f"[{ticker}] 신뢰도 {parsed['confidence']:.0%} < 임계값 {threshold:.0%} "
                    f"→ HOLD 다운그레이드 (원래: {parsed['action']})"
                )
                parsed["action"] = "HOLD"
                # confidence 유지 — 이미 낮은 값을 추가 감쇄하지 않음

            # 리스크 매니저 연동: BUY/STRONG_BUY인 경우 리스크 체크 (경고만, 차단 안함)
            if parsed["action"] in ("BUY", "STRONG_BUY"):
                try:
                    from analysis.risk_manager import risk_manager
                    sector = stock.sector if stock else None
                    risk_check = risk_manager.check_can_buy(ticker, sector)
                    if not risk_check["allowed"]:
                        logger.warning(
                            f"[{ticker}] 리스크 경고: {risk_check['reason']} "
                            f"(BUY 유지, reasoning에 메모)"
                        )
                        parsed["reasoning"] += f" [리스크 경고: {risk_check['reason']}]"
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
        5-Factor Scoring Model v2.0

        Factor Groups (각 0-10 정규화):
          F1. Trend Quality  — MA 정렬, MA 구조, 가격 위치
          F2. Momentum       — MACD, RSI zone, 5일 수익률(ROC)
          F3. Mean-Reversion — RSI 과매도, StochRSI, BB 위치/스퀴즈
          F4. Volume         — 거래량 비율, OBV 추세 (중립 기준선)
          F5. Trend Strength — ADX 수준

        개선사항 (v1 대비):
          - 모든 factor를 0-10 동일 스케일 정규화 → 불균형 해소
          - Volume: 중립 기준선 5.0 (v1은 91.7% 페널티 문제)
          - ADX: momentum/reversion 양쪽에 적용 (micro-regime)
          - MA200 penalty: momentum/reversion 양쪽 적용
          - Penalty: 모두 multiplicative로 통일
          - RSI 40-50 dead zone 해소
          - 섹터 다양성 캡 (최대 20%)
          - ROC(5일 수익률) 추가
        """
        from database.models import TechnicalIndicator, PriceHistory
        from datetime import timedelta
        from config.tickers import ALL_TICKERS, TICKER_INDEX

        # ETF 제외: 개별 주식만 스코어링 대상
        watchlist = [t for t in ALL_TICKERS if "ETF" not in TICKER_INDEX.get(t, [])]
        logger.info(f"[AI Priority v2] ETF 제외: {len(ALL_TICKERS)} → {len(watchlist)}개 개별 주식")

        # ── STEP 0: VIX Macro-Regime ──
        vix_level = 18.0
        regime_name = "trending"
        try:
            from data_fetcher.market_data import market_fetcher as _mf
            vix_data = _mf.fetch_realtime_price("^VIX")
            vix_level = vix_data["price"] if vix_data else 18.0
        except Exception:
            pass

        # VIX 기반 글로벌 가중치 (5 factor)
        if vix_level > 28:
            regime_name = "high_volatility"
            weights = {"trend": 0.15, "momentum": 0.10, "reversion": 0.40, "volume": 0.15, "strength": 0.20}
        elif vix_level > 20:
            regime_name = "transitional"
            weights = {"trend": 0.25, "momentum": 0.25, "reversion": 0.20, "volume": 0.15, "strength": 0.15}
        else:
            regime_name = "trending"
            weights = {"trend": 0.30, "momentum": 0.30, "reversion": 0.10, "volume": 0.15, "strength": 0.15}

        logger.debug(f"[Priority v2] Regime={regime_name} VIX={vix_level:.1f} weights={weights}")

        # ── STEP 1: Per-stock 5-factor scoring ──
        stock_scores: list[dict] = []

        with get_db() as db:
            latest_ind = db.query(TechnicalIndicator).order_by(TechnicalIndicator.date.desc()).first()
            cutoff_date = (
                latest_ind.date - timedelta(days=7)
                if latest_ind
                else datetime.now() - timedelta(days=14)
            )

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
                if not current_price:
                    continue

                # ═══════════════════════════════════════
                # F1: TREND QUALITY (0-10)
                # ═══════════════════════════════════════
                f_trend = 0.0

                # T1: MA Alignment — price vs MA20/50/200 (0-3)
                if ind.ma_20 and current_price > ind.ma_20:
                    f_trend += 1.0
                if ind.ma_50 and current_price > ind.ma_50:
                    f_trend += 1.0
                if ind.ma_200 and current_price > ind.ma_200:
                    f_trend += 1.0

                # T2: MA Structure — perfect stacking MA20 > MA50 > MA200 (+2)
                if (ind.ma_20 and ind.ma_50 and ind.ma_200
                        and ind.ma_20 > ind.ma_50 > ind.ma_200):
                    f_trend += 2.0

                # T3: MA50 > MA200 — Minervini 핵심 조건 (+1.5)
                if ind.ma_50 and ind.ma_200 and ind.ma_50 > ind.ma_200:
                    f_trend += 1.5

                # T4: MA200 Slope — 현재 MA200 vs 이전 MA200 비교 (+1.5)
                if (prev_ind and ind.ma_200 and prev_ind.ma_200
                        and ind.ma_200 > prev_ind.ma_200):
                    f_trend += 1.5  # MA200 상승 추세

                # T5: BB Position — 상단 근처 = 추세 확인 (+1)
                bb_pct = 50.0
                if (ind.bb_upper and ind.bb_lower
                        and (ind.bb_upper - ind.bb_lower) > 0):
                    bb_pct = (current_price - ind.bb_lower) / (ind.bb_upper - ind.bb_lower) * 100
                    if bb_pct > 70:
                        f_trend += 1.0

                f_trend = min(f_trend, 10.0)

                # ═══════════════════════════════════════
                # F2: MOMENTUM SIGNAL (0-10)
                # ═══════════════════════════════════════
                f_momentum = 0.0

                # Mo1: MACD Histogram (0-3)
                is_golden_cross = False
                macd_pts = 0.0
                if ind.macd_hist is not None:
                    if (prev_ind and prev_ind.macd_hist is not None
                            and prev_ind.macd_hist <= 0 < ind.macd_hist):
                        is_golden_cross = True
                        macd_pts = 3.0
                    elif ind.macd_hist > 0:
                        macd_pts = 1.5
                        if (prev_ind and prev_ind.macd_hist is not None
                                and ind.macd_hist > prev_ind.macd_hist):
                            macd_pts = 2.0  # Accelerating
                f_momentum += min(macd_pts, 3.0)

                # Mo2: RSI Momentum Zone (0-2.5) — dead zone 해소
                if ind.rsi_14 is not None:
                    if 55 <= ind.rsi_14 <= 65:
                        f_momentum += 2.5  # 최적 모멘텀 존
                    elif 50 <= ind.rsi_14 < 55:
                        f_momentum += 2.0
                    elif 45 <= ind.rsi_14 < 50:
                        f_momentum += 1.0  # v1에서 dead zone이었던 구간
                    elif 65 < ind.rsi_14 <= 70:
                        f_momentum += 1.5  # 강한 모멘텀 (과매수 직전)

                # Mo3: 5일 수익률 ROC (0-2.5)
                if len(price_rows) >= 5 and price_rows[4].close > 0:
                    roc_5d = (current_price - price_rows[4].close) / price_rows[4].close
                    if roc_5d > 0.05:
                        f_momentum += 2.5
                    elif roc_5d > 0.03:
                        f_momentum += 2.0
                    elif roc_5d > 0.01:
                        f_momentum += 1.0
                    elif roc_5d > 0:
                        f_momentum += 0.5

                # Mo4: Bull Trap Guard — golden cross 신뢰성 (multiplicative penalty)
                if is_golden_cross:
                    trap_factor = 1.0
                    if (latest_volume and ind.volume_ma_20
                            and latest_volume < ind.volume_ma_20 * 0.8):
                        trap_factor *= 0.7  # 거래량 미동반 → 30% 감소
                    if (ind.ma_20 and ind.ma_50
                            and current_price < ind.ma_20
                            and current_price < ind.ma_50):
                        trap_factor *= 0.6  # MA 아래에서 GC → 40% 추가 감소
                    f_momentum *= trap_factor

                f_momentum = min(f_momentum, 10.0)

                # ═══════════════════════════════════════
                # F3: MEAN-REVERSION (0-10)
                # ═══════════════════════════════════════
                f_reversion = 0.0

                # Re1: RSI Oversold (0-3.5)
                if ind.rsi_14 is not None:
                    if ind.rsi_14 < 25:
                        f_reversion += 3.5
                    elif ind.rsi_14 < 30:
                        f_reversion += 3.0
                    elif ind.rsi_14 < 35:
                        f_reversion += 2.0
                    elif ind.rsi_14 < 40:
                        f_reversion += 1.0

                # Re2: StochRSI Oversold Cross (0-2.5)
                if ind.stoch_rsi_k is not None and ind.stoch_rsi_d is not None:
                    if ind.stoch_rsi_k < 0.20 and ind.stoch_rsi_d < 0.20:
                        f_reversion += 1.0
                        if (prev_ind and prev_ind.stoch_rsi_k is not None
                                and prev_ind.stoch_rsi_d is not None
                                and prev_ind.stoch_rsi_k <= prev_ind.stoch_rsi_d
                                and ind.stoch_rsi_k > ind.stoch_rsi_d):
                            f_reversion += 1.5  # Bullish cross in oversold

                # Re3: BB Position — 하단 근처 (0-2.5)
                if bb_pct < 10:
                    f_reversion += 2.5
                elif bb_pct < 20:
                    f_reversion += 2.0
                elif bb_pct < 30:
                    f_reversion += 1.0

                # Re4: BB Squeeze (0-1.5)
                if (ind.bb_upper and ind.bb_lower and ind.bb_middle
                        and ind.bb_middle > 0
                        and prev_ind and prev_ind.bb_upper
                        and prev_ind.bb_lower and prev_ind.bb_middle
                        and prev_ind.bb_middle > 0):
                    bb_width = (ind.bb_upper - ind.bb_lower) / ind.bb_middle
                    prev_width = (prev_ind.bb_upper - prev_ind.bb_lower) / prev_ind.bb_middle
                    if bb_width < 0.04 and bb_width < prev_width:
                        f_reversion += 1.5
                    elif bb_width < 0.06:
                        f_reversion += 0.5

                f_reversion = min(f_reversion, 10.0)

                # ═══════════════════════════════════════
                # F4: VOLUME CONFIRMATION (0-10)
                # 중립 기준선 5.0 — v1의 91.7% 페널티 문제 해결
                # ═══════════════════════════════════════
                f_volume = 5.0  # NEUTRAL baseline

                if latest_volume and ind.volume_ma_20 and ind.volume_ma_20 > 0:
                    vr = latest_volume / ind.volume_ma_20
                    if vr > 2.5:
                        f_volume = 10.0  # 폭발적 거래량
                    elif vr > 2.0:
                        f_volume = 9.0
                    elif vr > 1.5:
                        f_volume = 8.0
                    elif vr > 1.2:
                        f_volume = 7.0
                    elif vr > 0.8:
                        f_volume = 5.0  # 정상 범위 → 중립
                    elif vr > 0.5:
                        f_volume = 4.0  # 약간 낮음 (경미한 감점)
                    else:
                        f_volume = 3.0  # 매우 낮음

                # OBV 추세 (±1.5 가감)
                if ind.obv is not None and prev_ind and prev_ind.obv is not None:
                    obv_chg = ind.obv - prev_ind.obv
                    price_chg = (
                        price_rows[0].close - price_rows[1].close
                        if len(price_rows) >= 2 else 0
                    )
                    if obv_chg > 0 and price_chg <= 0:
                        f_volume += 1.5  # Bullish divergence
                    elif obv_chg > 0 and price_chg > 0:
                        f_volume += 0.5  # Confirming
                    elif obv_chg < 0 and price_chg > 0:
                        f_volume -= 1.5  # Bearish divergence (대칭)

                f_volume = max(0.0, min(f_volume, 10.0))

                # ═══════════════════════════════════════
                # F5: TREND STRENGTH / ADX (0-10)
                # ═══════════════════════════════════════
                f_strength = 5.0  # 중립
                raw_adx = ind.adx_14

                if raw_adx is not None:
                    if raw_adx > 40:
                        f_strength = 10.0
                    elif raw_adx > 35:
                        f_strength = 9.0
                    elif raw_adx > 30:
                        f_strength = 8.0
                    elif raw_adx > 25:
                        f_strength = 7.0
                    elif raw_adx > 20:
                        f_strength = 5.0  # 중립
                    elif raw_adx > 15:
                        f_strength = 3.5
                    else:
                        f_strength = 2.0  # 추세 없음

                # ═══════════════════════════════════════
                # GLOBAL PENALTIES (multiplicative, 양쪽 적용)
                # ═══════════════════════════════════════
                penalty_mult = 1.0

                # P1: Falling Knife (연속 하락일)
                if len(price_rows) >= 4:
                    down_days = 0
                    for i in range(min(len(price_rows) - 1, 4)):
                        if price_rows[i].close < price_rows[i + 1].close:
                            down_days += 1
                        else:
                            break
                    if down_days >= 4:
                        penalty_mult *= 0.6
                    elif down_days >= 3:
                        penalty_mult *= 0.75

                # P2: Below MA200 — 양쪽 동시 감소 (v1은 reversion만)
                if ind.ma_200 and current_price < ind.ma_200:
                    f_momentum *= 0.5   # 약세 추세에서 momentum 신뢰도 ↓
                    f_reversion *= 0.7  # 약세지만 반등 가능성은 일부 유지

                # P3: Overbought Guard (RSI > 75)
                if ind.rsi_14 is not None and ind.rsi_14 > 75:
                    f_momentum *= 0.5
                    f_reversion *= 0.2

                # ═══════════════════════════════════════
                # ADX MICRO-REGIME (종목별 momentum/reversion 가중치 조정)
                # ═══════════════════════════════════════
                local_weights = dict(weights)  # copy global weights
                if raw_adx is not None:
                    if raw_adx > 30:
                        # 강한 추세 → momentum 가중 ↑, reversion 가중 ↓
                        local_weights["momentum"] = min(local_weights["momentum"] + 0.05, 0.40)
                        local_weights["reversion"] = max(local_weights["reversion"] - 0.05, 0.05)
                    elif raw_adx < 20:
                        # 비추세 (레인지) → reversion 가중 ↑, momentum 가중 ↓
                        local_weights["reversion"] = min(local_weights["reversion"] + 0.10, 0.45)
                        local_weights["momentum"] = max(local_weights["momentum"] - 0.10, 0.05)

                # 가중치 합계 정규화 (항상 1.0)
                w_sum = sum(local_weights.values())
                if w_sum > 0:
                    local_weights = {k: v / w_sum for k, v in local_weights.items()}

                # ═══════════════════════════════════════
                # COMPOSITE SCORE
                # ═══════════════════════════════════════
                composite = (
                    local_weights["trend"] * f_trend
                    + local_weights["momentum"] * f_momentum
                    + local_weights["reversion"] * f_reversion
                    + local_weights["volume"] * f_volume
                    + local_weights["strength"] * f_strength
                )
                composite *= penalty_mult
                composite = max(composite, 0.0)

                stock_scores.append({
                    "ticker": ticker,
                    "score": round(composite, 3),
                    "f_trend": round(f_trend, 1),
                    "f_momentum": round(f_momentum, 1),
                    "f_reversion": round(f_reversion, 1),
                    "f_volume": round(f_volume, 1),
                    "f_strength": round(f_strength, 1),
                    "category": TICKER_INDEX.get(ticker, []),
                })

        # ── STEP 2: 정렬 ──
        stock_scores.sort(key=lambda x: x["score"], reverse=True)

        # ── STEP 3: 섹터 다양성 캡 (최대 20%) ──
        sector_cap = max(3, max_count // 5)  # 50개 기준 = 10개/섹터
        sector_counts: dict[str, int] = {}
        selected: list[str] = []

        for item in stock_scores:
            if len(selected) >= max_count:
                break

            # 주요 카테고리 결정 (첫 번째 non-ETF 카테고리)
            categories = [c for c in item["category"] if c != "ETF"]
            primary_sector = categories[0] if categories else "OTHER"

            count = sector_counts.get(primary_sector, 0)
            if count >= sector_cap:
                continue  # 이 섹터 이미 한도 도달 → 스킵

            selected.append(item["ticker"])
            sector_counts[primary_sector] = count + 1

        # ── STEP 4: 로깅 ──
        scored_count = len(stock_scores)
        avg_score = sum(s["score"] for s in stock_scores) / scored_count if scored_count else 0
        logger.info(
            f"[AI Priority v2] Regime={regime_name} VIX={vix_level:.1f} | "
            f"Scored {scored_count}/{len(watchlist)} stocks | "
            f"avg={avg_score:.2f} | selected {len(selected)}"
        )
        if selected:
            top5_info = [
                next(s for s in stock_scores if s["ticker"] == t)
                for t in selected[:5]
            ]
            for s in top5_info:
                logger.debug(
                    f"  [{s['ticker']}] score={s['score']:.2f} "
                    f"T={s['f_trend']} M={s['f_momentum']} "
                    f"R={s['f_reversion']} V={s['f_volume']} S={s['f_strength']}"
                )
            logger.info(
                f"[AI Priority v2] Sector distribution: "
                + ", ".join(f"{k}={v}" for k, v in sorted(sector_counts.items(), key=lambda x: -x[1]))
            )

        return selected

    def analyze_all_watchlist(self) -> dict[str, str]:
        """
        watchlist 전체를 기술적 필터링 후 상위 50개 종목을 AI 분석합니다.
        유료 티어 전환 후 GEMINI_CALL_DELAY(기본 0.5초) 간격으로 호출하며,
        429 에러 시 GEMINI_BACKOFF_BASE 기반 지수 백오프를 적용합니다.

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
        import re as _re
        from google.api_core.exceptions import ResourceExhausted
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _parse_retry_delay(err) -> int:
            """구글 429 응답에서 retry_delay 초를 파싱"""
            m = _re.search(r"retry.*?(\d+)\.?\d*s", str(err), _re.IGNORECASE)
            return int(m.group(1)) + 1 if m else 0

        total = len(tickers)
        concurrency = settings.GEMINI_CONCURRENCY
        logger.info(f"[AI 분석] {total}개 종목 병렬 분석 시작 (동시 {concurrency}개)")

        def _analyze_one(idx_ticker):
            idx, ticker = idx_ticker
            # 스태거 딜레이: 동시 요청 폭주 방지 (인덱스 % 동시수 × 1초)
            stagger = (idx % concurrency) * 1.0
            if stagger > 0:
                time.sleep(stagger)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"[AI 분석] ({idx+1}/{total}) {ticker} 시도 중...")
                    rec = self.analyze_ticker(ticker)
                    return ticker, rec.action if rec else "ERROR"
                except ResourceExhausted as e:
                    if attempt < max_retries - 1:
                        wait = max(settings.GEMINI_BACKOFF_BASE * (2 ** attempt), _parse_retry_delay(e))
                        logger.warning(f"[{ticker}] API 할당량 초과(429). {wait}초 대기 후 재시도... ({attempt+1}/{max_retries})")
                        time.sleep(wait)
                    else:
                        logger.error(f"[{ticker}] 최대 재시도(3회) 실패(429 Error): {e}")
                        return ticker, "ERROR"
                except Exception as e:
                    if '429' in str(e) and attempt < max_retries - 1:
                        wait = max(settings.GEMINI_BACKOFF_BASE * (2 ** attempt), _parse_retry_delay(e))
                        logger.warning(f"[{ticker}] API 할당량 초과(429 str). {wait}초 대기 후 재시도... ({attempt+1}/{max_retries})")
                        time.sleep(wait)
                    else:
                        logger.error(f"[{ticker}] 분석 중 예외 발생: {e}")
                        return ticker, "ERROR"
            return ticker, "ERROR"

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(_analyze_one, (i, t)): t
                for i, t in enumerate(tickers)
            }
            for future in as_completed(futures):
                ticker, action = future.result()
                results[ticker] = action

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

    def get_top_picks(self, top_n: int = 3) -> list[dict]:
        """
        오늘의 BUY/STRONG_BUY 추천 중 복합 점수 기준 상위 N개를 반환합니다.

        복합 점수 = weighted_score * 0.40 + confidence * 10 * 0.25
                   + risk_reward_ratio * 0.20 + sentiment_score * 0.15

        Returns:
            상위 N개 추천 리스트 (딕셔너리)
        """
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        with get_db() as db:
            recs = (
                db.query(AIRecommendation)
                .filter(
                    AIRecommendation.recommendation_date >= today_start,
                    AIRecommendation.action.in_(["BUY", "STRONG_BUY"]),
                )
                .all()
            )

            if not recs:
                logger.info("[Top Picks] 오늘 BUY/STRONG_BUY 추천이 없습니다.")
                return []

            scored = []
            for r in recs:
                stock = db.query(Stock).filter(Stock.id == r.stock_id).first()
                ticker = stock.ticker if stock else "?"
                name = stock.name if stock else "?"

                # 개별 점수 (None → 0 처리)
                ts = r.technical_score or 0.0
                fs = r.fundamental_score or 0.0
                ss = r.sentiment_score or 0.0
                conf = r.confidence or 0.0

                # weighted_score 계산 (DB에 없으면 직접 계산)
                weighted = ts * 0.45 + fs * 0.30 + ss * 0.25

                # 리스크/리워드 비율 (target_price / stop_loss 기반)
                rr_ratio = 0.0
                if r.target_price and r.stop_loss and r.price_at_recommendation:
                    upside = r.target_price - r.price_at_recommendation
                    downside = r.price_at_recommendation - r.stop_loss
                    if downside > 0:
                        rr_ratio = min(upside / downside, 5.0)  # 최대 5로 캡

                # 복합 점수 (0~10 스케일)
                composite = (
                    weighted * 0.40
                    + conf * 10 * 0.25
                    + rr_ratio * 0.20
                    + ss * 0.15
                )

                # STRONG_BUY 보너스 (+0.5)
                if r.action == "STRONG_BUY":
                    composite += 0.5

                scored.append({
                    "rank": 0,
                    "ticker": ticker,
                    "name": name,
                    "action": r.action,
                    "composite_score": round(composite, 2),
                    "confidence": round(conf, 2),
                    "weighted_score": round(weighted, 2),
                    "technical_score": round(ts, 1),
                    "fundamental_score": round(fs, 1),
                    "sentiment_score": round(ss, 1),
                    "risk_reward_ratio": round(rr_ratio, 2),
                    "target_price": r.target_price,
                    "stop_loss": r.stop_loss,
                    "price_at_recommendation": r.price_at_recommendation,
                    "reasoning": r.reasoning,
                })

            # 복합 점수 기준 내림차순 정렬
            scored.sort(key=lambda x: x["composite_score"], reverse=True)

            # 순위 부여 및 상위 N개 선택
            for i, pick in enumerate(scored[:top_n]):
                pick["rank"] = i + 1

            top = scored[:top_n]
            logger.info(
                f"[Top Picks] {len(recs)}개 BUY 중 상위 {len(top)}개 선정: "
                + ", ".join(f"{p['ticker']}({p['composite_score']})" for p in top)
            )
            return top

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
