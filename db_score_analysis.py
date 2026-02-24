"""
DB Score Distribution Analysis Script
Reproduces get_priority_tickers() scoring logic and analyzes score distribution.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import statistics
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from database.connection import get_db
from database.models import Stock, TechnicalIndicator, PriceHistory, AIRecommendation
from config.tickers import ALL_TICKERS, TICKER_INDEX


def compute_scores():
    """Reproduce get_priority_tickers() scoring for ALL stocks (not just top 50)."""
    watchlist = [t for t in ALL_TICKERS if "ETF" not in TICKER_INDEX.get(t, [])]
    print(f"=== SCORING UNIVERSE ===")
    print(f"ALL_TICKERS: {len(ALL_TICKERS)}")
    print(f"After ETF exclusion: {len(watchlist)}")

    # We'll use a fixed regime for analysis (default trending)
    # But first let's detect what regime the algo would use
    regime_mom_w = 0.70
    regime_rev_w = 0.30
    regime_name = "trending"

    # Try to get VIX but fall back to default
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
        print(f"VIX level: {vix_level:.1f}")
    except Exception as e:
        vix_level = 18.0
        print(f"VIX detection failed ({e}), using default trending regime")

    print(f"Regime: {regime_name} (mom_w={regime_mom_w}, rev_w={regime_rev_w})")
    print()

    all_scores = {}
    sub_scores = {}  # ticker -> {momentum, reversion, vol_mult, obv_bonus, knife_pen, final}
    indicator_data = {}  # ticker -> indicator values for analysis

    with get_db() as db:
        # Find latest indicator date
        latest_ind = db.query(TechnicalIndicator).order_by(TechnicalIndicator.date.desc()).first()
        if latest_ind:
            cutoff_date = latest_ind.date - timedelta(days=7)
            print(f"Latest indicator date: {latest_ind.date}")
            print(f"Cutoff date: {cutoff_date}")
        else:
            cutoff_date = datetime.now() - timedelta(days=14)
            print(f"No indicators found, using cutoff: {cutoff_date}")

        no_stock = 0
        no_ind = 0
        no_price = 0
        processed = 0

        for ticker in watchlist:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                no_stock += 1
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
                no_ind += 1
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
                no_price += 1
                continue

            current_price = price_rows[0].close
            latest_volume = price_rows[0].volume
            processed += 1

            # === MOMENTUM SUB-SCORE ===
            momentum = 0.0

            # M1: MA Alignment (0-4)
            ma_count = 0
            if current_price and ind.ma_20 and current_price > ind.ma_20: ma_count += 1
            if current_price and ind.ma_50 and current_price > ind.ma_50: ma_count += 1
            if current_price and ind.ma_200 and current_price > ind.ma_200: ma_count += 1
            if ind.ma_20 and ind.ma_50 and ind.ma_200 and ind.ma_20 > ind.ma_50 > ind.ma_200:
                ma_count += 1
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
                        macd_pts = 2.0
            momentum += min(macd_pts, 3.0)

            # M3: ADX multiplier
            adx_mult = 1.0
            if ind.adx_14 is not None:
                if ind.adx_14 > 30: adx_mult = 1.3
                elif ind.adx_14 > 25: adx_mult = 1.15
                elif ind.adx_14 < 20: adx_mult = 0.7
            momentum *= adx_mult

            # M4: RSI Momentum Zone
            if ind.rsi_14 is not None and 50 <= ind.rsi_14 <= 65:
                momentum += 1.5

            # === MEAN-REVERSION SUB-SCORE ===
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
                        reversion += 1.0

            # R3: BB Position (0-2.5)
            bb_pct = None
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

            # === VOLUME MULTIPLIER ===
            vol_mult = 1.0
            if latest_volume and ind.volume_ma_20 and ind.volume_ma_20 > 0:
                vr = latest_volume / ind.volume_ma_20
                if vr > 2.0: vol_mult = 1.4
                elif vr > 1.3: vol_mult = 1.2
                elif vr < 0.5: vol_mult = 0.6
                elif vr < 0.8: vol_mult = 0.8

            # === OBV DIVERGENCE ===
            obv_bonus = 0.0
            if ind.obv is not None and prev_ind and prev_ind.obv is not None:
                obv_chg = ind.obv - prev_ind.obv
                price_chg = price_rows[0].close - price_rows[1].close if len(price_rows) >= 2 else 0
                if obv_chg > 0 and price_chg <= 0:
                    obv_bonus = 1.5
                elif obv_chg > 0 and price_chg > 0:
                    obv_bonus = 0.5
                elif obv_chg < 0 and price_chg > 0:
                    obv_bonus = -1.0

            # === PENALTIES ===
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

            # Below MA200
            below_ma200 = False
            if current_price and ind.ma_200 and current_price < ind.ma_200:
                reversion *= 0.5
                below_ma200 = True

            # Bull trap
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

            # Overbought guard
            overbought = False
            if ind.rsi_14 is not None and ind.rsi_14 > 75:
                momentum *= 0.5
                reversion *= 0.2
                overbought = True

            # === FINAL SCORE ===
            raw = regime_mom_w * momentum + regime_rev_w * reversion
            adjusted = raw * vol_mult + obv_bonus
            final = adjusted * (1.0 - knife_pen)
            final = max(final, 0.0)

            all_scores[ticker] = round(final, 4)
            sub_scores[ticker] = {
                "momentum": round(momentum, 4),
                "reversion": round(reversion, 4),
                "vol_mult": round(vol_mult, 2),
                "obv_bonus": round(obv_bonus, 2),
                "knife_pen": round(knife_pen, 2),
                "raw": round(raw, 4),
                "adjusted": round(adjusted, 4),
                "final": round(final, 4),
            }
            indicator_data[ticker] = {
                "rsi_14": ind.rsi_14,
                "macd_hist": ind.macd_hist,
                "adx_14": ind.adx_14,
                "bb_pct": bb_pct,
                "ma_20": ind.ma_20,
                "ma_50": ind.ma_50,
                "ma_200": ind.ma_200,
                "volume_ma_20": ind.volume_ma_20,
                "current_price": current_price,
                "latest_volume": latest_volume,
                "obv": ind.obv,
                "stoch_rsi_k": ind.stoch_rsi_k,
                "stoch_rsi_d": ind.stoch_rsi_d,
                "below_ma200": below_ma200,
                "overbought": overbought,
                "is_golden_cross": is_golden_cross,
            }

        print(f"\n=== DATA AVAILABILITY ===")
        print(f"Stocks without DB record: {no_stock}")
        print(f"Stocks without recent indicators: {no_ind}")
        print(f"Stocks without price data: {no_price}")
        print(f"Successfully processed: {processed}")

        # Get today's AI recommendations
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        ai_recs = {}
        recs = (
            db.query(AIRecommendation)
            .filter(AIRecommendation.recommendation_date >= today_start)
            .all()
        )
        for r in recs:
            stock = db.query(Stock).filter(Stock.id == r.stock_id).first()
            if stock:
                ai_recs[stock.ticker] = {
                    "action": r.action,
                    "confidence": r.confidence,
                    "technical_score": r.technical_score,
                    "fundamental_score": r.fundamental_score,
                    "sentiment_score": r.sentiment_score,
                }

        # If no today recs, try most recent date
        if not ai_recs:
            print("No today's AI recommendations found, looking for most recent...")
            latest_rec = (
                db.query(AIRecommendation)
                .order_by(AIRecommendation.recommendation_date.desc())
                .first()
            )
            if latest_rec:
                rec_date_start = latest_rec.recommendation_date.replace(hour=0, minute=0, second=0, microsecond=0)
                recs = (
                    db.query(AIRecommendation)
                    .filter(AIRecommendation.recommendation_date >= rec_date_start)
                    .all()
                )
                for r in recs:
                    stock = db.query(Stock).filter(Stock.id == r.stock_id).first()
                    if stock:
                        ai_recs[stock.ticker] = {
                            "action": r.action,
                            "confidence": r.confidence,
                            "technical_score": r.technical_score,
                            "fundamental_score": r.fundamental_score,
                            "sentiment_score": r.sentiment_score,
                        }
                print(f"Using recommendations from: {rec_date_start} ({len(ai_recs)} recs)")

    return all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w


def analyze_distribution(all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w):
    """Comprehensive analysis of score distribution."""

    scores_list = list(all_scores.values())
    tickers_list = list(all_scores.keys())

    # ============================================================
    # 1. OVERALL SCORE DISTRIBUTION
    # ============================================================
    print("\n" + "=" * 70)
    print("1. OVERALL SCORE DISTRIBUTION")
    print("=" * 70)

    if not scores_list:
        print("No scores computed!")
        return

    print(f"Total stocks scored: {len(scores_list)}")
    print(f"  Min:    {min(scores_list):.4f}")
    print(f"  Max:    {max(scores_list):.4f}")
    print(f"  Mean:   {statistics.mean(scores_list):.4f}")
    print(f"  Median: {statistics.median(scores_list):.4f}")
    print(f"  StdDev: {statistics.stdev(scores_list):.4f}" if len(scores_list) > 1 else "  StdDev: N/A")

    # Percentiles
    sorted_scores = sorted(scores_list)
    n = len(sorted_scores)
    for pct in [10, 25, 50, 75, 90]:
        idx = int(n * pct / 100)
        idx = min(idx, n - 1)
        print(f"  P{pct:2d}:    {sorted_scores[idx]:.4f}")

    # Threshold analysis
    above_05 = sum(1 for s in scores_list if s > 0.5)
    below_05 = sum(1 for s in scores_list if s <= 0.5)
    zero_scores = sum(1 for s in scores_list if s == 0.0)
    print(f"\n  Threshold 0.5:")
    print(f"    Above 0.5: {above_05} ({above_05/len(scores_list)*100:.1f}%)")
    print(f"    At or below 0.5: {below_05} ({below_05/len(scores_list)*100:.1f}%)")
    print(f"    Exactly 0.0: {zero_scores} ({zero_scores/len(scores_list)*100:.1f}%)")

    # Histogram
    bins = [(0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 100)]
    print(f"\n  Score Histogram:")
    for lo, hi in bins:
        count = sum(1 for s in scores_list if lo <= s < hi)
        bar = "#" * min(count, 60)
        label = f"{lo:.1f}-{hi:.1f}" if hi < 100 else f"{lo:.1f}+"
        print(f"    [{label:>8s}]: {count:4d} {bar}")

    # ============================================================
    # 2. SUB-SCORE ANALYSIS
    # ============================================================
    print("\n" + "=" * 70)
    print("2. SUB-SCORE ANALYSIS")
    print("=" * 70)

    mom_scores = [sub_scores[t]["momentum"] for t in sub_scores]
    rev_scores = [sub_scores[t]["reversion"] for t in sub_scores]
    vol_mults = [sub_scores[t]["vol_mult"] for t in sub_scores]
    obv_bonuses = [sub_scores[t]["obv_bonus"] for t in sub_scores]

    print(f"\n  Momentum Sub-Score:")
    print(f"    Min:    {min(mom_scores):.4f}")
    print(f"    Max:    {max(mom_scores):.4f}")
    print(f"    Mean:   {statistics.mean(mom_scores):.4f}")
    print(f"    Median: {statistics.median(mom_scores):.4f}")
    print(f"    Zero:   {sum(1 for m in mom_scores if m == 0)}/{len(mom_scores)} ({sum(1 for m in mom_scores if m == 0)/len(mom_scores)*100:.1f}%)")

    print(f"\n  Reversion Sub-Score:")
    print(f"    Min:    {min(rev_scores):.4f}")
    print(f"    Max:    {max(rev_scores):.4f}")
    print(f"    Mean:   {statistics.mean(rev_scores):.4f}")
    print(f"    Median: {statistics.median(rev_scores):.4f}")
    print(f"    Zero:   {sum(1 for r in rev_scores if r == 0)}/{len(rev_scores)} ({sum(1 for r in rev_scores if r == 0)/len(rev_scores)*100:.1f}%)")

    # Correlation: both high
    both_high = sum(1 for t in sub_scores if sub_scores[t]["momentum"] > 3 and sub_scores[t]["reversion"] > 2)
    print(f"\n  Correlation (mom>3 AND rev>2): {both_high} stocks")

    # Which dominates?
    mom_dominant = sum(1 for t in sub_scores if sub_scores[t]["momentum"] > sub_scores[t]["reversion"])
    rev_dominant = sum(1 for t in sub_scores if sub_scores[t]["reversion"] > sub_scores[t]["momentum"])
    equal = sum(1 for t in sub_scores if sub_scores[t]["momentum"] == sub_scores[t]["reversion"])
    print(f"  Momentum dominant: {mom_dominant} ({mom_dominant/len(sub_scores)*100:.1f}%)")
    print(f"  Reversion dominant: {rev_dominant} ({rev_dominant/len(sub_scores)*100:.1f}%)")
    print(f"  Equal: {equal}")

    print(f"\n  Volume Multiplier Distribution:")
    vol_counts = Counter(vol_mults)
    for v in sorted(vol_counts.keys()):
        print(f"    {v:.1f}x: {vol_counts[v]} stocks")

    print(f"\n  OBV Bonus Distribution:")
    obv_counts = Counter(obv_bonuses)
    for v in sorted(obv_counts.keys()):
        label = {1.5: "Bullish divergence", 0.5: "Confirming uptrend", 0.0: "No signal", -1.0: "Bearish divergence"}.get(v, str(v))
        print(f"    {v:+.1f} ({label}): {obv_counts[v]} stocks")

    # Knife penalty
    knife_applied = sum(1 for t in sub_scores if sub_scores[t]["knife_pen"] > 0)
    print(f"\n  Falling Knife Penalty Applied: {knife_applied} stocks")
    for pen_val in [0.25, 0.4]:
        cnt = sum(1 for t in sub_scores if sub_scores[t]["knife_pen"] == pen_val)
        if cnt > 0:
            print(f"    Penalty {pen_val}: {cnt} stocks")

    # ============================================================
    # 3. TOP 50 vs REST COMPARISON
    # ============================================================
    print("\n" + "=" * 70)
    print("3. TOP 50 vs REST COMPARISON")
    print("=" * 70)

    sorted_tickers = sorted(all_scores, key=lambda t: all_scores[t], reverse=True)
    top50 = sorted_tickers[:50]
    rest = sorted_tickers[50:]

    def avg_indicator(tickers, field):
        vals = [indicator_data[t][field] for t in tickers if t in indicator_data and indicator_data[t][field] is not None]
        return statistics.mean(vals) if vals else None

    fields = ["rsi_14", "macd_hist", "adx_14", "bb_pct"]
    print(f"\n  {'Indicator':<15} {'Top 50':>12} {'Rest':>12} {'Delta':>12}")
    print(f"  {'-'*15} {'-'*12} {'-'*12} {'-'*12}")
    for f in fields:
        top_avg = avg_indicator(top50, f)
        rest_avg = avg_indicator(rest, f)
        if top_avg is not None and rest_avg is not None:
            delta = top_avg - rest_avg
            print(f"  {f:<15} {top_avg:>12.2f} {rest_avg:>12.2f} {delta:>+12.2f}")
        else:
            print(f"  {f:<15} {'N/A':>12} {'N/A':>12} {'N/A':>12}")

    # Sub-scores comparison
    print(f"\n  {'Sub-Score':<15} {'Top 50':>12} {'Rest':>12} {'Delta':>12}")
    print(f"  {'-'*15} {'-'*12} {'-'*12} {'-'*12}")
    for sf in ["momentum", "reversion", "vol_mult", "obv_bonus"]:
        top_vals = [sub_scores[t][sf] for t in top50 if t in sub_scores]
        rest_vals = [sub_scores[t][sf] for t in rest if t in sub_scores]
        top_avg = statistics.mean(top_vals) if top_vals else 0
        rest_avg = statistics.mean(rest_vals) if rest_vals else 0
        delta = top_avg - rest_avg
        print(f"  {sf:<15} {top_avg:>12.4f} {rest_avg:>12.4f} {delta:>+12.4f}")

    # MA200 position
    top50_above_ma200 = sum(1 for t in top50 if t in indicator_data and not indicator_data[t]["below_ma200"])
    rest_above_ma200 = sum(1 for t in rest if t in indicator_data and not indicator_data[t]["below_ma200"])
    top50_total = sum(1 for t in top50 if t in indicator_data)
    rest_total = sum(1 for t in rest if t in indicator_data)
    print(f"\n  Above MA200:")
    print(f"    Top 50: {top50_above_ma200}/{top50_total} ({top50_above_ma200/top50_total*100:.1f}%)" if top50_total else "    Top 50: N/A")
    print(f"    Rest:   {rest_above_ma200}/{rest_total} ({rest_above_ma200/rest_total*100:.1f}%)" if rest_total else "    Rest: N/A")

    # Golden cross
    top50_gc = sum(1 for t in top50 if t in indicator_data and indicator_data[t]["is_golden_cross"])
    rest_gc = sum(1 for t in rest if t in indicator_data and indicator_data[t]["is_golden_cross"])
    print(f"\n  Golden Cross (MACD):")
    print(f"    Top 50: {top50_gc}")
    print(f"    Rest:   {rest_gc}")

    # Top 50 score range
    print(f"\n  Top 50 Score Range: {all_scores[top50[0]]:.4f} ~ {all_scores[top50[-1]]:.4f}")
    print(f"  Top 10:")
    for t in top50[:10]:
        s = sub_scores[t]
        ind_d = indicator_data.get(t, {})
        print(f"    {t:>6s}: final={all_scores[t]:.2f} mom={s['momentum']:.2f} rev={s['reversion']:.2f} "
              f"vol={s['vol_mult']:.1f} obv={s['obv_bonus']:+.1f} "
              f"RSI={ind_d.get('rsi_14', 'N/A')}")

    print(f"  Bottom 5 of Top 50:")
    for t in top50[-5:]:
        s = sub_scores[t]
        ind_d = indicator_data.get(t, {})
        print(f"    {t:>6s}: final={all_scores[t]:.2f} mom={s['momentum']:.2f} rev={s['reversion']:.2f} "
              f"vol={s['vol_mult']:.1f} obv={s['obv_bonus']:+.1f} "
              f"RSI={ind_d.get('rsi_14', 'N/A')}")

    # ============================================================
    # 4. SECTOR / CATEGORY BIAS
    # ============================================================
    print("\n" + "=" * 70)
    print("4. SECTOR / CATEGORY BIAS")
    print("=" * 70)

    # Category distribution of top 50
    cat_counts_top50 = Counter()
    cat_counts_all = Counter()
    for t in top50:
        cats = TICKER_INDEX.get(t, [])
        for c in cats:
            if c != "ETF":
                cat_counts_top50[c] += 1

    for t in all_scores:
        cats = TICKER_INDEX.get(t, [])
        for c in cats:
            if c != "ETF":
                cat_counts_all[c] += 1

    print(f"\n  Category Distribution (Top 50 vs All Scored):")
    print(f"  {'Category':<15} {'Top50':>6} {'All':>6} {'Top50%':>8} {'All%':>8} {'Over/Under':>12}")
    print(f"  {'-'*15} {'-'*6} {'-'*6} {'-'*8} {'-'*8} {'-'*12}")
    for cat in ["NASDAQ100", "SP500", "MIDCAP", "SMALLCAP"]:
        t50 = cat_counts_top50.get(cat, 0)
        all_c = cat_counts_all.get(cat, 0)
        t50_pct = t50 / 50 * 100 if top50 else 0
        all_pct = all_c / len(all_scores) * 100 if all_scores else 0
        over = t50_pct - all_pct
        print(f"  {cat:<15} {t50:>6} {all_c:>6} {t50_pct:>7.1f}% {all_pct:>7.1f}% {over:>+11.1f}%")

    # ============================================================
    # 5. AI JUDGMENT CORRELATION
    # ============================================================
    print("\n" + "=" * 70)
    print("5. AI JUDGMENT vs PRIORITY SCORE")
    print("=" * 70)

    if not ai_recs:
        print("  No AI recommendations found for analysis period.")
    else:
        print(f"  Total AI recommendations: {len(ai_recs)}")

        buy_tickers = [t for t, r in ai_recs.items() if r["action"] in ("BUY", "STRONG_BUY")]
        hold_tickers = [t for t, r in ai_recs.items() if r["action"] == "HOLD"]

        print(f"  BUY/STRONG_BUY: {len(buy_tickers)}")
        print(f"  HOLD: {len(hold_tickers)}")

        buy_scores = [all_scores[t] for t in buy_tickers if t in all_scores]
        hold_scores = [all_scores[t] for t in hold_tickers if t in all_scores]

        if buy_scores:
            print(f"\n  BUY Priority Scores:")
            print(f"    Min:    {min(buy_scores):.4f}")
            print(f"    Max:    {max(buy_scores):.4f}")
            print(f"    Mean:   {statistics.mean(buy_scores):.4f}")
            print(f"    Median: {statistics.median(buy_scores):.4f}")

        if hold_scores:
            print(f"\n  HOLD Priority Scores:")
            print(f"    Min:    {min(hold_scores):.4f}")
            print(f"    Max:    {max(hold_scores):.4f}")
            print(f"    Mean:   {statistics.mean(hold_scores):.4f}")
            print(f"    Median: {statistics.median(hold_scores):.4f}")

        # High priority but HOLD
        high_priority_hold = [(t, all_scores.get(t, 0)) for t in hold_tickers
                              if t in all_scores and all_scores[t] > 3.0]
        if high_priority_hold:
            high_priority_hold.sort(key=lambda x: x[1], reverse=True)
            print(f"\n  HIGH Priority Score but HOLD ({len(high_priority_hold)} stocks):")
            for t, s in high_priority_hold[:10]:
                r = ai_recs[t]
                ind_d = indicator_data.get(t, {})
                print(f"    {t:>6s}: priority={s:.2f} conf={r['confidence']:.2f} "
                      f"tech={r.get('technical_score', 'N/A')} "
                      f"RSI={ind_d.get('rsi_14', 'N/A')}")

        # Low priority but BUY
        low_priority_buy = [(t, all_scores.get(t, 0)) for t in buy_tickers
                            if t in all_scores and all_scores[t] < 2.0]
        if low_priority_buy:
            low_priority_buy.sort(key=lambda x: x[1])
            print(f"\n  LOW Priority Score but BUY ({len(low_priority_buy)} stocks):")
            for t, s in low_priority_buy[:10]:
                r = ai_recs[t]
                ind_d = indicator_data.get(t, {})
                print(f"    {t:>6s}: priority={s:.2f} conf={r['confidence']:.2f} "
                      f"tech={r.get('technical_score', 'N/A')} "
                      f"RSI={ind_d.get('rsi_14', 'N/A')}")

        # Action breakdown for top 50 vs rest
        top50_set = set(top50)
        buy_in_top50 = sum(1 for t in buy_tickers if t in top50_set)
        buy_outside_top50 = sum(1 for t in buy_tickers if t not in top50_set)
        print(f"\n  BUY Distribution:")
        print(f"    In Top 50:      {buy_in_top50}")
        print(f"    Outside Top 50: {buy_outside_top50}")

        # Confidence distribution by action
        for action_type in ["STRONG_BUY", "BUY", "HOLD"]:
            tickers_of_type = [t for t, r in ai_recs.items() if r["action"] == action_type]
            if tickers_of_type:
                confs = [ai_recs[t]["confidence"] for t in tickers_of_type]
                print(f"\n  {action_type} Confidence: mean={statistics.mean(confs):.3f} "
                      f"min={min(confs):.3f} max={max(confs):.3f} count={len(confs)}")

    # ============================================================
    # 6. FACTOR IMPORTANCE ANALYSIS
    # ============================================================
    print("\n" + "=" * 70)
    print("6. FACTOR IMPORTANCE (what drives selection into Top 50?)")
    print("=" * 70)

    top50_set = set(top50)
    # For each factor, compute average for top50 vs rest
    factors = {
        "MA Alignment (above MA20/50/200)": lambda t: (
            (1 if indicator_data[t]["current_price"] and indicator_data[t]["ma_20"] and indicator_data[t]["current_price"] > indicator_data[t]["ma_20"] else 0) +
            (1 if indicator_data[t]["current_price"] and indicator_data[t]["ma_50"] and indicator_data[t]["current_price"] > indicator_data[t]["ma_50"] else 0) +
            (1 if indicator_data[t]["current_price"] and indicator_data[t]["ma_200"] and indicator_data[t]["current_price"] > indicator_data[t]["ma_200"] else 0)
        ),
        "RSI in 50-65 zone": lambda t: 1 if indicator_data[t]["rsi_14"] and 50 <= indicator_data[t]["rsi_14"] <= 65 else 0,
        "RSI oversold (<40)": lambda t: 1 if indicator_data[t]["rsi_14"] and indicator_data[t]["rsi_14"] < 40 else 0,
        "MACD Hist > 0": lambda t: 1 if indicator_data[t]["macd_hist"] is not None and indicator_data[t]["macd_hist"] > 0 else 0,
        "ADX > 25": lambda t: 1 if indicator_data[t]["adx_14"] is not None and indicator_data[t]["adx_14"] > 25 else 0,
        "BB pct < 30": lambda t: 1 if indicator_data[t]["bb_pct"] is not None and indicator_data[t]["bb_pct"] < 30 else 0,
    }

    print(f"\n  {'Factor':<35} {'Top50%':>8} {'Rest%':>8} {'Lift':>8}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*8}")
    for name, fn in factors.items():
        top_vals = []
        rest_vals = []
        for t in all_scores:
            if t not in indicator_data:
                continue
            try:
                val = fn(t)
                if t in top50_set:
                    top_vals.append(val)
                else:
                    rest_vals.append(val)
            except:
                pass
        top_pct = statistics.mean(top_vals) * 100 if top_vals else 0
        rest_pct = statistics.mean(rest_vals) * 100 if rest_vals else 0
        lift = top_pct - rest_pct
        print(f"  {name:<35} {top_pct:>7.1f}% {rest_pct:>7.1f}% {lift:>+7.1f}%")


if __name__ == "__main__":
    all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w = compute_scores()
    analyze_distribution(all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w)
