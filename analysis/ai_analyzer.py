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

SYSTEM_PROMPT = """You are an expert US stock market analyst specializing in technical and fundamental analysis.
Analyze the provided stock data and generate a buy recommendation.

IMPORTANT: Only base your analysis on the provided data. Do not assume or fabricate any information not given. If data is insufficient, reflect that in lower confidence.

CRITICAL: Respond ONLY with valid JSON matching this exact schema:
{
    "action": "STRONG_BUY" | "BUY" | "HOLD",
    "confidence": <float 0.0-1.0>,
    "target_price": <float or null>,
    "stop_loss": <float or null>,
    "technical_score": <float 0.0-10.0>,
    // 0-2: Strong bearish (RSI>70, MACD dead cross, below all MAs)
    // 3-4: Weak bearish / neutral-bearish
    // 5: Neutral / mixed signals
    // 6-7: Moderate bullish (RSI recovering, MACD positive, above MA20/50)
    // 8-10: Strong bullish (golden cross, breakout confirmed with volume)
    "fundamental_score": <float 0.0-10.0>,
    // 0-2: Overvalued (PE>40, negative margins, high debt)
    // 3-4: Fairly valued with concerns
    // 5: Fair value
    // 6-7: Undervalued (PE<20, positive FCF, moderate growth)
    // 8-10: Deeply undervalued with strong catalysts
    "sentiment_score": <float 0.0-10.0>,
    // 0-2: Extremely negative news, analyst downgrades
    // 5: Neutral / no significant news
    // 8-10: Very positive catalysts, analyst upgrades
    "reasoning": "<string, max 500 chars, in English>",
    "key_factors": ["<factor1>", "<factor2>", ...],
    "risks": ["<risk1>", "<risk2>", ...]
}

Guidelines:
- STRONG_BUY: confidence >= 0.80, clear bullish signals across multiple indicators
- BUY: confidence >= 0.65, moderate bullish signals
- HOLD: insufficient bullish evidence or mixed signals
- reasoning must be in English for consistency
- target_price and stop_loss should be realistic based on current price and volatility"""


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
        """컨텍스트 데이터를 분석 프롬프트로 변환합니다."""
        stock = context.get("stock", {})
        prices = context.get("prices", [])
        ind = context.get("indicators", {})
        news = context.get("news", [])
        current_price = context.get("current_price")

        prompt_parts = [
            f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M')} ET",
            "",
            f"## Stock: {stock.get('ticker')} - {stock.get('name')}",
            f"Sector: {stock.get('sector')} | Industry: {stock.get('industry')}",
            f"Market Cap: ${stock.get('market_cap', 0):,.0f}" if stock.get("market_cap") else "Market Cap: N/A",
            f"Current Price: ${current_price}" if current_price else "",
            "",
            "## Recent 35-Day Price Data (OHLCV):",
            json.dumps(prices, separators=(',', ':')),
            "",
            "## Latest Technical Indicators:",
            json.dumps(ind, indent=2),
            "",
        ]

        # Short Interest & Ownership
        short_ratio = stock.get("short_ratio")
        short_pct = stock.get("short_pct_of_float")
        inst_pct = context.get("fundamentals", {}).get("held_pct_institutions")
        insider_pct = context.get("fundamentals", {}).get("held_pct_insiders")

        ownership_lines = []
        if short_ratio is not None:
            ownership_lines.append(f"- Short Ratio: {short_ratio:.1f} days to cover")
        if short_pct is not None:
            ownership_lines.append(f"- Short % of Float: {short_pct:.1%}")
        if inst_pct is not None:
            ownership_lines.append(f"- Institutional Ownership: {inst_pct:.1%}")
        if insider_pct is not None:
            ownership_lines.append(f"- Insider Ownership: {insider_pct:.1%}")
        if ownership_lines:
            prompt_parts.extend(["## Ownership & Short Interest:"] + ownership_lines + [""])

        # 재무 데이터 (Fundamental Data)
        fundamentals = context.get("fundamentals", {})
        if fundamentals:
            fund_lines = ["## Fundamental Data:"]
            fund_labels = {
                "pe_ratio": "P/E (trailing)",
                "forward_pe": "P/E (forward)",
                "pb_ratio": "P/B",
                "ps_ratio": "P/S",
                "dividend_yield": "Dividend Yield",
                "eps_trailing": "EPS (trailing)",
                "eps_forward": "EPS (forward)",
                "revenue_growth": "Revenue Growth",
                "profit_margin": "Profit Margin",
                "debt_to_equity": "Debt/Equity",
                "roe": "ROE",
                "free_cash_flow": "Free Cash Flow",
            }
            for key, label in fund_labels.items():
                val = fundamentals.get(key)
                if val is not None:
                    if key in ("dividend_yield", "revenue_growth", "profit_margin", "roe"):
                        fund_lines.append(f"- {label}: {val:.2%}" if isinstance(val, (int, float)) else f"- {label}: {val}")
                    elif key == "free_cash_flow":
                        fund_lines.append(f"- {label}: ${val:,.0f}" if isinstance(val, (int, float)) else f"- {label}: {val}")
                    else:
                        fund_lines.append(f"- {label}: {val}")
            prompt_parts.extend(fund_lines + [""])

        if ind:
            # 기술적 신호 요약
            rsi = ind.get("rsi_14")
            macd_hist = ind.get("macd_hist")
            macd_crossover = ind.get("macd_crossover")
            bb_upper = ind.get("bb_upper")
            bb_lower = ind.get("bb_lower")
            ma_20 = ind.get("ma_20")
            ma_50 = ind.get("ma_50")

            signals = []
            if rsi is not None:
                if rsi < 30:
                    signals.append(f"RSI={rsi:.1f} (below 30 threshold)")
                elif rsi > 70:
                    signals.append(f"RSI={rsi:.1f} (above 70 threshold)")
                else:
                    signals.append(f"RSI={rsi:.1f} (neutral)")
            # MACD: 방향 전환 우선 표시 [E]
            if macd_crossover == "GOLDEN_CROSS":
                signals.append(f"MACD Histogram: crossed from negative to positive ({macd_hist:.4f})")
            elif macd_crossover == "DEAD_CROSS":
                signals.append(f"MACD Histogram: crossed from positive to negative ({macd_hist:.4f})")
            elif macd_hist is not None:
                signals.append(f"MACD Histogram={'positive' if macd_hist > 0 else 'negative'} ({macd_hist:.4f})")
            if current_price and bb_upper and bb_lower:
                bb_pct = (current_price - bb_lower) / (bb_upper - bb_lower) * 100 if (bb_upper - bb_lower) != 0 else 50
                signals.append(f"Bollinger Band position: {bb_pct:.1f}% (0%=lower, 100%=upper)")
            if current_price and ma_20:
                pct_from_ma20 = (current_price - ma_20) / ma_20 * 100
                signals.append(f"Price vs MA20: {pct_from_ma20:+.2f}%")
            if current_price and ma_50:
                pct_from_ma50 = (current_price - ma_50) / ma_50 * 100
                signals.append(f"Price vs MA50: {pct_from_ma50:+.2f}%")

            adx = ind.get("adx_14")
            if adx is not None:
                if adx > 25:
                    signals.append(f"ADX={adx:.1f} (strong trend)")
                elif adx > 20:
                    signals.append(f"ADX={adx:.1f} (developing trend)")
                else:
                    signals.append(f"ADX={adx:.1f} (weak/no trend, range-bound)")

            if signals:
                prompt_parts.extend(["## Technical Signal Summary:", *[f"- {s}" for s in signals], ""])

        # 시장 국면 [G]
        market_ctx = context.get("market_context", {})
        if market_ctx:
            market_lines = ["## Market Context:"]
            spy = market_ctx.get("SPY")
            qqq = market_ctx.get("QQQ")
            vix = market_ctx.get("^VIX")
            if spy:
                trend = "bullish" if spy["change_pct"] > 0 else "bearish"
                market_lines.append(f"- SPY: ${spy['price']:.2f} ({spy['change_pct']:+.2f}%) — {trend}")
            if qqq:
                trend = "bullish" if qqq["change_pct"] > 0 else "bearish"
                market_lines.append(f"- QQQ: ${qqq['price']:.2f} ({qqq['change_pct']:+.2f}%) — {trend}")
            if vix:
                vix_level = "HIGH(fear)" if vix["price"] > 30 else ("ELEVATED(caution)" if vix["price"] > 20 else "LOW(stable)")
                market_lines.append(f"- VIX: {vix['price']:.2f} ({vix_level})")
            tnx = market_ctx.get("^TNX")
            if tnx:
                rate_env = "high-rate environment" if tnx["price"] > 4.5 else ("moderate rates" if tnx["price"] > 3.0 else "low rates")
                market_lines.append(f"- 10Y Treasury Yield: {tnx['price']:.2f}% ({rate_env})")
            prompt_parts.extend(market_lines + [""])

        # 실적발표일 경고 [K]
        earnings_warning = context.get("earnings_warning")
        if earnings_warning:
            prompt_parts.extend([f"## Earnings Alert: {earnings_warning}", ""])

        # 백테스팅 과거 성과 [C]
        past_perf = context.get("past_performance", {})
        overall = past_perf.get("overall", {})
        if overall.get("with_outcomes", 0) and overall["with_outcomes"] > 0:
            perf_lines = [
                "## AI Past Performance (last 90 days):",
                f"- Recommendations with outcomes: {overall['with_outcomes']}",
            ]
            if overall.get("win_rate") is not None:
                perf_lines.append(f"- Win rate: {overall['win_rate']:.1f}%")
            if overall.get("avg_return") is not None:
                perf_lines.append(f"- Avg return: {overall['avg_return']:.2f}%")
            if past_perf.get("by_action"):
                perf_lines.append("- By action:")
                for ab in past_perf["by_action"]:
                    perf_lines.append(
                        f"  - {ab['action']}: win_rate={ab['win_rate']:.1f}%, avg_return={ab['avg_return']:.2f}%"
                    )
            prompt_parts.extend(perf_lines + [""])

        if news:
            prompt_parts.append("## Recent News (sentiment: -1.0 negative to +1.0 positive):")
            for n in news:
                sentiment_str = f"sentiment={n['sentiment']}" if n["sentiment"] is not None else "sentiment=N/A"
                prompt_parts.append(f"- [{n.get('published_at', 'N/A')}] {n['title']} ({sentiment_str})")
            prompt_parts.append("")

        prompt_parts.append(
            "Based on all the above data, provide your buy recommendation as JSON."
        )

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

            # 1. VIX 신뢰도 감쇄 (시그모이드 기반)
            vix_data = context.get("market_context", {}).get("^VIX")
            if vix_data:
                vix_level = vix_data.get("price")
                if vix_level is not None and vix_level > 20:
                    import math
                    normalized = (vix_level - 20) / 15  # 0 at VIX=20, 1 at VIX=35
                    vix_penalty = 0.3 * (1 / (1 + math.exp(-3 * (normalized - 0.5))))
                    parsed["confidence"] = round(parsed["confidence"] * (1 - vix_penalty), 2)

            # 2. 신뢰도 임계값 체크 (VIX 조정 후 최종 게이트)
            threshold = settings.BUY_CONFIDENCE_THRESHOLD
            if parsed["action"] in ("BUY", "STRONG_BUY") and parsed["confidence"] < threshold:
                logger.info(
                    f"[{ticker}] 신뢰도 {parsed['confidence']:.0%} < 임계값 {threshold:.0%} "
                    f"→ HOLD 다운그레이드 (원래: {parsed['action']})"
                )
                parsed["action"] = "HOLD"
                parsed["confidence"] = round(parsed["confidence"] * 0.7, 2)

            # 3. VIX 극단적 수준에서 STRONG_BUY 다운그레이드만
            if vix_data:
                vix_level = vix_data.get("price")
                if vix_level is not None and vix_level > 35 and parsed["action"] == "STRONG_BUY":
                    parsed["action"] = "BUY"
                    logger.info(f"[{ticker}] VIX {vix_level:.1f} > 35 → BUY 다운그레이드")

            # 신뢰도 보정: 과거 백테스팅 정확도 반영
            try:
                from analysis.backtester import backtester as _bt
                breakdown = _bt.get_action_breakdown(days=90)
                action_stats = {b["action"]: b for b in breakdown}
                if parsed["action"] in action_stats:
                    hist_win_rate = action_stats[parsed["action"]]["win_rate"] / 100.0
                    calibrated = 0.7 * parsed["confidence"] + 0.3 * hist_win_rate
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
        기술적 조건을 만족하는 상위 N개 종목을 선별합니다.

        선별 기준 (점수 기반):
          - RSI < 35: 과매도 (강력 매수 신호) → +3점
          - RSI < 45: 저RSI (매수 고려) → +1점
          - MACD Histogram > 0 (골든크로스 방향) → +2점
          - 현재가 > MA20 (상승 추세) → +1점
          - 현재가 > MA50 (중기 상승) → +1점
          - 볼린저밴드 하단 근처 (BB pct < 25%) → +2점

        DB에 저장된 TechnicalIndicator를 스캔하므로 API 호출 없음.
        Gemini API 호출은 선별된 상위 max_count개에만 적용.
        """
        from database.models import TechnicalIndicator, PriceHistory
        from datetime import timedelta

        watchlist = settings.WATCHLIST_TICKERS
        scores: dict[str, float] = {}

        cutoff_date = datetime.now() - timedelta(days=3)  # 최근 3일 이내 지표만 유효

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

                # 최신 종가 조회
                latest_price_row = (
                    db.query(PriceHistory)
                    .filter(
                        PriceHistory.stock_id == stock.id,
                        PriceHistory.interval == "1d",
                    )
                    .order_by(PriceHistory.timestamp.desc())
                    .first()
                )
                current_price = latest_price_row.close if latest_price_row else None

                score = 0.0

                # RSI 신호 (떨어지는 칼 방지: RSI<35이면서 MA200 아래이면 점수 추가 안 함)
                below_ma200 = (current_price and ind.ma_200 and current_price < ind.ma_200)
                if ind.rsi_14 is not None:
                    if ind.rsi_14 < 35:
                        if not below_ma200:
                            score += 2.0
                        else:
                            logger.debug(f"[{ticker}] RSI={ind.rsi_14:.1f} < 35이지만 MA200 아래 → 점수 미부여 (떨어지는 칼 방지)")
                    elif ind.rsi_14 < 45:
                        score += 1.0

                # MACD 방향 전환 스코어링 [E] (골든크로스 시 거래량 조건 추가)
                if ind.macd_hist is not None and ind.macd_hist > 0:
                    prev_ind_row = (
                        db.query(TechnicalIndicator)
                        .filter(
                            TechnicalIndicator.stock_id == stock.id,
                            TechnicalIndicator.date < ind.date,
                        )
                        .order_by(TechnicalIndicator.date.desc())
                        .first()
                    )
                    if prev_ind_row and prev_ind_row.macd_hist is not None and prev_ind_row.macd_hist <= 0:
                        # 골든크로스 발생: 거래량 >= VMA20이면 +3, 아니면 +1
                        latest_volume = latest_price_row.volume if latest_price_row else None
                        if latest_volume and ind.volume_ma_20 and latest_volume >= ind.volume_ma_20:
                            score += 3.0  # 골든크로스 + 거래량 수반
                        else:
                            score += 1.0  # 골든크로스이지만 거래량 부족
                    else:
                        score += 2.0  # 양수 유지 (상승 모멘텀)

                # 이동평균 신호
                if current_price and ind.ma_20 and current_price > ind.ma_20:
                    score += 1.0
                if current_price and ind.ma_50 and current_price > ind.ma_50:
                    score += 1.0

                # MA200 장기 추세 스코어링 [F]
                if current_price and ind.ma_200:
                    if current_price > ind.ma_200:
                        score += 2.0   # 장기 상승 추세
                    else:
                        score -= 1.0   # 장기 하락 추세 페널티

                # ADX 추세 강도 보너스
                if ind.adx_14 is not None:
                    if ind.adx_14 > 25:
                        score += 2.0   # 강한 추세 진행 중
                    elif ind.adx_14 > 20:
                        score += 1.0   # 보통 추세

                # RSI 모멘텀 존 (50-65) - 상승 추세 중 건전한 영역
                if ind.rsi_14 is not None and 50 <= ind.rsi_14 <= 65:
                    if current_price and ind.ma_50 and current_price > ind.ma_50:
                        score += 2.0   # 상승 추세 + 건전한 RSI

                # 볼린저밴드 하단 근처 — 거래량 조건부 스코어링 [H]
                if (current_price and ind.bb_upper and ind.bb_lower and
                        (ind.bb_upper - ind.bb_lower) > 0):
                    bb_pct = (current_price - ind.bb_lower) / (ind.bb_upper - ind.bb_lower) * 100
                    if bb_pct < 25:
                        latest_volume = latest_price_row.volume if latest_price_row else None
                        if latest_volume and ind.volume_ma_20 and latest_volume < ind.volume_ma_20:
                            score += 1.0   # 거래량 감소: 하락 지속 가능
                        else:
                            score += 2.0   # 거래량 정상/증가: 반등 신호 유효

                if score > 0:
                    scores[ticker] = score

        # 점수 내림차순 정렬, 상위 max_count개 선택
        sorted_tickers = sorted(scores, key=lambda t: scores[t], reverse=True)
        selected = sorted_tickers[:max_count]

        logger.info(
            f"[AI 우선순위] 전체 {len(watchlist)}개 중 지표 데이터 있는 종목: {len(scores)}개, "
            f"상위 {len(selected)}개 선별 완료"
        )
        if selected:
            top5 = [(t, f"{scores[t]:.1f}점") for t in selected[:5]]
            logger.debug(f"[AI 우선순위] 상위 5개: {top5}")

        return selected

    def analyze_all_watchlist(self) -> dict[str, str]:
        """
        watchlist 전체를 기술적 필터링 후 상위 50개 종목만 AI 분석합니다.
        전체 종목이 많을 경우(>50개) get_priority_tickers()로 우선순위 선별.

        Returns:
            {ticker: action} 딕셔너리
        """
        results = {}
        all_tickers = settings.WATCHLIST_TICKERS

        # 50개 초과 시 우선순위 필터 적용
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
        for i, ticker in enumerate(tickers):
            try:
                rec = self.analyze_ticker(ticker)
                results[ticker] = rec.action if rec else "ERROR"
            except Exception as e:
                logger.error(f"[{ticker}] 분석 중 예외 발생: {e}")
                results[ticker] = "ERROR"
            # Rate limit: API 호출 간 2초 대기
            if i < len(tickers) - 1:
                time.sleep(2)

        buy_count = sum(1 for a in results.values() if a in ("BUY", "STRONG_BUY"))
        logger.info(f"[AI 분석] 완료 — 매수 추천: {buy_count}/{len(tickers)}개")
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
