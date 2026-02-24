"""
Supplemental DB Score Analysis - covers items 7 & 8 from task assignment,
plus deeper breakdowns for items 2 (sector/market cap bias) and 6 (hit rate).
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


def compute_all_scores():
    """Reproduce get_priority_tickers() scoring for ALL stocks."""
    watchlist = [t for t in ALL_TICKERS if "ETF" not in TICKER_INDEX.get(t, [])]

    regime_mom_w = 0.70
    regime_rev_w = 0.30
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
    except Exception:
        vix_level = 18.0

    all_scores = {}
    sub_scores = {}
    indicator_data = {}

    with get_db() as db:
        latest_ind = db.query(TechnicalIndicator).order_by(TechnicalIndicator.date.desc()).first()
        cutoff_date = latest_ind.date - timedelta(days=7) if latest_ind else datetime.now() - timedelta(days=14)

        for ticker in watchlist:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                continue

            ind = (
                db.query(TechnicalIndicator)
                .filter(TechnicalIndicator.stock_id == stock.id, TechnicalIndicator.date >= cutoff_date)
                .order_by(TechnicalIndicator.date.desc())
                .first()
            )
            if ind is None:
                continue

            prev_ind = (
                db.query(TechnicalIndicator)
                .filter(TechnicalIndicator.stock_id == stock.id, TechnicalIndicator.date < ind.date)
                .order_by(TechnicalIndicator.date.desc())
                .first()
            )

            price_rows = (
                db.query(PriceHistory)
                .filter(PriceHistory.stock_id == stock.id, PriceHistory.interval == "1d")
                .order_by(PriceHistory.timestamp.desc())
                .limit(6)
                .all()
            )
            if not price_rows:
                continue

            current_price = price_rows[0].close
            latest_volume = price_rows[0].volume

            # MOMENTUM
            momentum = 0.0
            ma_count = 0
            if current_price and ind.ma_20 and current_price > ind.ma_20: ma_count += 1
            if current_price and ind.ma_50 and current_price > ind.ma_50: ma_count += 1
            if current_price and ind.ma_200 and current_price > ind.ma_200: ma_count += 1
            if ind.ma_20 and ind.ma_50 and ind.ma_200 and ind.ma_20 > ind.ma_50 > ind.ma_200:
                ma_count += 1
            momentum += min(ma_count, 4)

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

            adx_mult = 1.0
            if ind.adx_14 is not None:
                if ind.adx_14 > 30: adx_mult = 1.3
                elif ind.adx_14 > 25: adx_mult = 1.15
                elif ind.adx_14 < 20: adx_mult = 0.7
            momentum *= adx_mult

            if ind.rsi_14 is not None and 50 <= ind.rsi_14 <= 65:
                momentum += 1.5

            # REVERSION
            reversion = 0.0
            if ind.rsi_14 is not None:
                if ind.rsi_14 < 25: reversion += 3.0
                elif ind.rsi_14 < 30: reversion += 2.5
                elif ind.rsi_14 < 35: reversion += 1.5
                elif ind.rsi_14 < 40: reversion += 0.5

            if ind.stoch_rsi_k is not None and ind.stoch_rsi_d is not None:
                if ind.stoch_rsi_k < 0.20 and ind.stoch_rsi_d < 0.20:
                    reversion += 1.0
                    if (prev_ind and prev_ind.stoch_rsi_k is not None
                            and prev_ind.stoch_rsi_d is not None
                            and prev_ind.stoch_rsi_k <= prev_ind.stoch_rsi_d
                            and ind.stoch_rsi_k > ind.stoch_rsi_d):
                        reversion += 1.0

            bb_pct = None
            if (current_price and ind.bb_upper and ind.bb_lower
                    and (ind.bb_upper - ind.bb_lower) > 0):
                bb_pct = (current_price - ind.bb_lower) / (ind.bb_upper - ind.bb_lower) * 100
                if bb_pct < 10: reversion += 2.5
                elif bb_pct < 20: reversion += 2.0
                elif bb_pct < 30: reversion += 1.0

            if (ind.bb_upper and ind.bb_lower and ind.bb_middle and ind.bb_middle > 0
                    and prev_ind and prev_ind.bb_upper and prev_ind.bb_lower
                    and prev_ind.bb_middle and prev_ind.bb_middle > 0):
                bb_width = (ind.bb_upper - ind.bb_lower) / ind.bb_middle
                prev_width = (prev_ind.bb_upper - prev_ind.bb_lower) / prev_ind.bb_middle
                if bb_width < 0.04 and bb_width < prev_width:
                    reversion += 1.5
                elif bb_width < 0.06:
                    reversion += 0.5

            # VOLUME
            vol_mult = 1.0
            vol_ratio = None
            if latest_volume and ind.volume_ma_20 and ind.volume_ma_20 > 0:
                vol_ratio = latest_volume / ind.volume_ma_20
                if vol_ratio > 2.0: vol_mult = 1.4
                elif vol_ratio > 1.3: vol_mult = 1.2
                elif vol_ratio < 0.5: vol_mult = 0.6
                elif vol_ratio < 0.8: vol_mult = 0.8

            # OBV
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

            # PENALTIES
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

            if current_price and ind.ma_200 and current_price < ind.ma_200:
                reversion *= 0.5

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

            if ind.rsi_14 is not None and ind.rsi_14 > 75:
                momentum *= 0.5
                reversion *= 0.2

            # FINAL
            raw = regime_mom_w * momentum + regime_rev_w * reversion
            adjusted = raw * vol_mult + obv_bonus
            final = adjusted * (1.0 - knife_pen)
            final = max(final, 0.0)

            # Also compute score WITHOUT vol_mult and WITHOUT obv_bonus for counterfactual
            raw_no_vol_obv = raw * 1.0 + 0.0  # vol_mult=1.0, obv_bonus=0
            final_no_vol_obv = raw_no_vol_obv * (1.0 - knife_pen)
            final_no_vol_obv = max(final_no_vol_obv, 0.0)

            all_scores[ticker] = round(final, 4)
            sub_scores[ticker] = {
                "momentum": round(momentum, 4),
                "reversion": round(reversion, 4),
                "vol_mult": round(vol_mult, 2),
                "vol_ratio": round(vol_ratio, 4) if vol_ratio else None,
                "obv_bonus": round(obv_bonus, 2),
                "knife_pen": round(knife_pen, 2),
                "raw": round(raw, 4),
                "final": round(final, 4),
                "final_no_vol_obv": round(final_no_vol_obv, 4),
            }
            indicator_data[ticker] = {
                "rsi_14": ind.rsi_14,
                "macd_hist": ind.macd_hist,
                "adx_14": ind.adx_14,
                "bb_pct": bb_pct,
                "current_price": current_price,
                "latest_volume": latest_volume,
                "volume_ma_20": ind.volume_ma_20,
                "sector": stock.sector,
                "market_cap": stock.market_cap,
            }

        # AI recommendations
        ai_recs = {}
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        recs = db.query(AIRecommendation).filter(AIRecommendation.recommendation_date >= today_start).all()
        if not recs:
            latest_rec = db.query(AIRecommendation).order_by(AIRecommendation.recommendation_date.desc()).first()
            if latest_rec:
                rec_date_start = latest_rec.recommendation_date.replace(hour=0, minute=0, second=0, microsecond=0)
                recs = db.query(AIRecommendation).filter(AIRecommendation.recommendation_date >= rec_date_start).all()
        for r in recs:
            stock = db.query(Stock).filter(Stock.id == r.stock_id).first()
            if stock:
                ai_recs[stock.ticker] = {"action": r.action, "confidence": r.confidence}

    return all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w, vix_level


def run_supplemental_analysis(all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w, vix_level):
    scores_list = list(all_scores.values())
    sorted_tickers = sorted(all_scores, key=lambda t: all_scores[t], reverse=True)
    top50 = set(sorted_tickers[:50])

    # ============================================================
    # ITEM 2: SECTOR + MARKET CAP BIAS (deeper)
    # ============================================================
    print("=" * 70)
    print("SECTOR BIAS ANALYSIS (Top 50 vs All)")
    print("=" * 70)

    sector_top50 = Counter()
    sector_all = Counter()
    for t in all_scores:
        sect = indicator_data.get(t, {}).get("sector") or "Unknown"
        sector_all[sect] += 1
        if t in top50:
            sector_top50[sect] += 1

    print(f"\n  {'Sector':<30} {'Top50':>5} {'All':>5} {'Top50%':>7} {'All%':>7} {'Over/Under':>12}")
    print(f"  {'-'*30} {'-'*5} {'-'*5} {'-'*7} {'-'*7} {'-'*12}")
    for sect in sorted(sector_all.keys(), key=lambda s: sector_top50.get(s, 0), reverse=True):
        t50 = sector_top50.get(sect, 0)
        total = sector_all[sect]
        t50_pct = t50 / 50 * 100
        all_pct = total / len(all_scores) * 100
        over = t50_pct - all_pct
        print(f"  {sect:<30} {t50:>5} {total:>5} {t50_pct:>6.1f}% {all_pct:>6.1f}% {over:>+11.1f}%")

    # Market Cap distribution
    print(f"\n--- Market Cap Distribution ---")

    def mcap_bucket(mcap):
        if mcap is None: return "Unknown"
        if mcap >= 200e9: return "Mega (>200B)"
        if mcap >= 10e9: return "Large (10-200B)"
        if mcap >= 2e9: return "Mid (2-10B)"
        return "Small (<2B)"

    mcap_top50 = Counter()
    mcap_all = Counter()
    for t in all_scores:
        mc = indicator_data.get(t, {}).get("market_cap")
        bucket = mcap_bucket(mc)
        mcap_all[bucket] += 1
        if t in top50:
            mcap_top50[bucket] += 1

    print(f"\n  {'Market Cap':<20} {'Top50':>5} {'All':>5} {'Top50%':>7} {'All%':>7} {'Over/Under':>12}")
    print(f"  {'-'*20} {'-'*5} {'-'*5} {'-'*7} {'-'*7} {'-'*12}")
    for bucket in ["Mega (>200B)", "Large (10-200B)", "Mid (2-10B)", "Small (<2B)", "Unknown"]:
        t50 = mcap_top50.get(bucket, 0)
        total = mcap_all.get(bucket, 0)
        if total == 0: continue
        t50_pct = t50 / 50 * 100
        all_pct = total / len(all_scores) * 100
        over = t50_pct - all_pct
        print(f"  {bucket:<20} {t50:>5} {total:>5} {t50_pct:>6.1f}% {all_pct:>6.1f}% {over:>+11.1f}%")

    # ============================================================
    # ITEM 5: VIX / REGIME WEIGHT EFFECT
    # ============================================================
    print(f"\n{'=' * 70}")
    print(f"VIX / REGIME WEIGHT ANALYSIS")
    print(f"{'=' * 70}")
    print(f"\n  Current VIX: {vix_level}")
    print(f"  Current Regime: {regime_name}")
    print(f"  Weights: momentum={regime_mom_w:.2f}, reversion={regime_rev_w:.2f}")

    # Simulate what top 50 would look like under different regimes
    for sim_name, sim_mom, sim_rev in [("trending", 0.70, 0.30), ("transitional", 0.45, 0.55), ("high_volatility", 0.25, 0.75)]:
        sim_scores = {}
        for t in sub_scores:
            s = sub_scores[t]
            raw_sim = sim_mom * s["momentum"] + sim_rev * s["reversion"]
            adj_sim = raw_sim * s["vol_mult"] + s["obv_bonus"]
            fin_sim = adj_sim * (1.0 - s["knife_pen"])
            fin_sim = max(fin_sim, 0.0)
            sim_scores[t] = fin_sim
        sim_sorted = sorted(sim_scores, key=lambda t: sim_scores[t], reverse=True)
        sim_top50 = set(sim_sorted[:50])

        overlap_with_current = len(top50 & sim_top50)
        sim_buy = [t for t in sim_top50 if t in ai_recs and ai_recs[t]["action"] in ("BUY", "STRONG_BUY")]
        current_marker = " <-- CURRENT" if sim_name == regime_name else ""
        print(f"\n  Regime: {sim_name} (mom={sim_mom}, rev={sim_rev}){current_marker}")
        print(f"    Overlap with current Top 50: {overlap_with_current}/50")
        print(f"    Top 5: {[(t, round(sim_scores[t], 2)) for t in sim_sorted[:5]]}")
        print(f"    BUY hits in this top 50: {len(sim_buy)}/50")

    # ============================================================
    # ITEM 6: TOP 50 -> BUY HIT RATE (detailed)
    # ============================================================
    print(f"\n{'=' * 70}")
    print(f"TOP 50 -> BUY HIT RATE (AI Accuracy)")
    print(f"{'=' * 70}")

    if ai_recs:
        total_recs = len(ai_recs)
        buy_recs = sum(1 for r in ai_recs.values() if r["action"] in ("BUY", "STRONG_BUY"))
        hold_recs = sum(1 for r in ai_recs.values() if r["action"] == "HOLD")

        print(f"\n  AI analyzed: {total_recs} stocks (= Top 50 sent to AI)")
        print(f"  BUY/STRONG_BUY: {buy_recs} ({buy_recs/total_recs*100:.1f}%)")
        print(f"  HOLD:           {hold_recs} ({hold_recs/total_recs*100:.1f}%)")

        # Score distribution comparison within Top 50
        buy_scores_in_top = [all_scores[t] for t in ai_recs if ai_recs[t]["action"] in ("BUY", "STRONG_BUY") and t in all_scores]
        hold_scores_in_top = [all_scores[t] for t in ai_recs if ai_recs[t]["action"] == "HOLD" and t in all_scores]

        if buy_scores_in_top and hold_scores_in_top:
            print(f"\n  Within Top 50, Priority Score comparison:")
            print(f"    BUY:  mean={statistics.mean(buy_scores_in_top):.3f}, median={statistics.median(buy_scores_in_top):.3f}")
            print(f"    HOLD: mean={statistics.mean(hold_scores_in_top):.3f}, median={statistics.median(hold_scores_in_top):.3f}")
            print(f"    Difference: {statistics.mean(buy_scores_in_top) - statistics.mean(hold_scores_in_top):+.3f}")

        # Score rank vs AI decision
        print(f"\n  Score Rank vs AI Decision (within Top 50):")
        print(f"  {'Rank':>6} {'Ticker':>8} {'Score':>8} {'Action':>12} {'Confidence':>12}")
        print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*12} {'-'*12}")
        for i, t in enumerate(sorted_tickers[:50]):
            if t in ai_recs:
                r = ai_recs[t]
                marker = " ***" if r["action"] in ("BUY", "STRONG_BUY") else ""
                print(f"  {i+1:>6} {t:>8} {all_scores[t]:>8.2f} {r['action']:>12} {r['confidence']:>11.2f}{marker}")
    else:
        print("  No AI recommendations found.")

    # ============================================================
    # ITEM 7: NATURAL CUTOFF POINT ANALYSIS
    # ============================================================
    print(f"\n{'=' * 70}")
    print(f"THRESHOLD / NATURAL CUTOFF ANALYSIS")
    print(f"{'=' * 70}")

    sorted_scores = sorted(scores_list, reverse=True)

    # Score gaps analysis - find largest gaps between consecutive scores
    print(f"\n  --- Score Gap Analysis (largest gaps in sorted scores) ---")
    gaps = []
    for i in range(len(sorted_scores) - 1):
        gap = sorted_scores[i] - sorted_scores[i + 1]
        gaps.append((i + 1, sorted_scores[i], sorted_scores[i + 1], gap))

    gaps.sort(key=lambda x: x[3], reverse=True)
    print(f"  {'Rank':>6} {'Above':>8} {'Below':>8} {'Gap':>8} {'Cutoff would select N':>24}")
    print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*24}")
    for rank, above, below, gap in gaps[:15]:
        print(f"  {rank:>6} {above:>8.3f} {below:>8.3f} {gap:>8.3f} {rank:>24}")

    # Threshold sensitivity
    print(f"\n  --- Threshold Sensitivity ---")
    print(f"  {'Threshold':>10} {'Passing':>8} {'% of Total':>12} {'Would select if top50':>24}")
    print(f"  {'-'*10} {'-'*8} {'-'*12} {'-'*24}")
    for threshold in [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]:
        passing = sum(1 for s in scores_list if s > threshold)
        pct = passing / len(scores_list) * 100
        top_n = min(passing, 50)
        print(f"  {threshold:>10.2f} {passing:>8} {pct:>11.1f}% {top_n:>24}")

    # Jenks natural breaks approximation (find where density drops)
    print(f"\n  --- Score Density (count per 0.25 bin) ---")
    for start in [i * 0.25 for i in range(20)]:
        end = start + 0.25
        count = sum(1 for s in scores_list if start <= s < end)
        bar = "#" * min(count, 50)
        print(f"  [{start:>5.2f}-{end:>5.2f}): {count:>4} {bar}")

    # ============================================================
    # ITEM 8: VOLUME MULTIPLIER & OBV BONUS RANK IMPACT
    # ============================================================
    print(f"\n{'=' * 70}")
    print(f"VOLUME MULTIPLIER & OBV BONUS RANK IMPACT")
    print(f"{'=' * 70}")

    # Counterfactual: What would rankings be WITHOUT vol_mult and obv_bonus?
    counterfactual_scores = {t: sub_scores[t]["final_no_vol_obv"] for t in sub_scores}
    cf_sorted = sorted(counterfactual_scores, key=lambda t: counterfactual_scores[t], reverse=True)
    cf_top50 = set(cf_sorted[:50])

    actual_top50 = top50
    overlap = len(actual_top50 & cf_top50)
    gained = actual_top50 - cf_top50  # in actual but not counterfactual
    lost = cf_top50 - actual_top50    # in counterfactual but not actual

    print(f"\n  --- Counterfactual: Scores without Vol Mult & OBV Bonus ---")
    print(f"  Overlap with actual Top 50: {overlap}/50")
    print(f"  Gained by vol/obv (in actual, not in CF): {len(gained)} stocks")
    print(f"  Lost by vol/obv (in CF, not in actual):   {len(lost)} stocks")

    if gained:
        print(f"\n  Stocks GAINED by volume/OBV effects:")
        for t in sorted(gained, key=lambda t: all_scores[t], reverse=True)[:10]:
            s = sub_scores[t]
            print(f"    {t:>8}: actual={s['final']:.2f} cf={s['final_no_vol_obv']:.2f} "
                  f"vol={s['vol_mult']:.1f} obv={s['obv_bonus']:+.1f} "
                  f"rank_change=+{cf_sorted.index(t)+1 - sorted_tickers.index(t)-1}")

    if lost:
        print(f"\n  Stocks LOST by volume/OBV effects:")
        for t in sorted(lost, key=lambda t: counterfactual_scores[t], reverse=True)[:10]:
            s = sub_scores[t]
            print(f"    {t:>8}: actual={s['final']:.2f} cf={s['final_no_vol_obv']:.2f} "
                  f"vol={s['vol_mult']:.1f} obv={s['obv_bonus']:+.1f} "
                  f"rank_change={cf_sorted.index(t)+1 - sorted_tickers.index(t)-1}")

    # Rank correlation (Spearman-like)
    actual_ranks = {t: i for i, t in enumerate(sorted_tickers)}
    cf_ranks = {t: i for i, t in enumerate(cf_sorted)}
    common = set(actual_ranks.keys()) & set(cf_ranks.keys())
    rank_diffs = [abs(actual_ranks[t] - cf_ranks[t]) for t in common]
    avg_rank_change = statistics.mean(rank_diffs)
    max_rank_change = max(rank_diffs)
    max_rank_ticker = max(common, key=lambda t: abs(actual_ranks[t] - cf_ranks[t]))

    print(f"\n  --- Rank Displacement Statistics ---")
    print(f"  Average rank change: {avg_rank_change:.1f} positions")
    print(f"  Max rank change:     {max_rank_change} positions ({max_rank_ticker})")
    print(f"  Median rank change:  {statistics.median(rank_diffs):.0f} positions")

    # Volume ratio distribution deep dive
    print(f"\n  --- Volume Ratio Distribution (latest_vol / vol_ma_20) ---")
    vol_ratios = [sub_scores[t]["vol_ratio"] for t in sub_scores if sub_scores[t]["vol_ratio"] is not None]
    if vol_ratios:
        print(f"  Total with volume data: {len(vol_ratios)}")
        print(f"  Min:    {min(vol_ratios):.4f}")
        print(f"  Max:    {max(vol_ratios):.4f}")
        print(f"  Mean:   {statistics.mean(vol_ratios):.4f}")
        print(f"  Median: {statistics.median(vol_ratios):.4f}")
        print(f"  P10:    {sorted(vol_ratios)[int(len(vol_ratios)*0.1)]:.4f}")
        print(f"  P25:    {sorted(vol_ratios)[int(len(vol_ratios)*0.25)]:.4f}")
        print(f"  P75:    {sorted(vol_ratios)[int(len(vol_ratios)*0.75)]:.4f}")
        print(f"  P90:    {sorted(vol_ratios)[int(len(vol_ratios)*0.9)]:.4f}")

        print(f"\n  Volume Ratio Buckets:")
        vol_buckets = [
            (0, 0.3, "Very Low (<0.3x)"),
            (0.3, 0.5, "Low (0.3-0.5x)  -> 0.6x mult"),
            (0.5, 0.8, "Below Avg (0.5-0.8x) -> 0.8x mult"),
            (0.8, 1.3, "Normal (0.8-1.3x) -> 1.0x mult"),
            (1.3, 2.0, "Above Avg (1.3-2.0x) -> 1.2x mult"),
            (2.0, 100, "High (>2.0x) -> 1.4x mult"),
        ]
        for lo, hi, label in vol_buckets:
            count = sum(1 for v in vol_ratios if lo <= v < hi)
            pct = count / len(vol_ratios) * 100
            bar = "#" * min(count, 40)
            print(f"    {label:<38} {count:>4} ({pct:>5.1f}%) {bar}")

    # OBV signal analysis
    print(f"\n  --- OBV Signal Frequency ---")
    obv_vals = [sub_scores[t]["obv_bonus"] for t in sub_scores]
    no_prev = sum(1 for t in sub_scores if sub_scores[t]["obv_bonus"] == 0.0)
    bull_div = sum(1 for t in sub_scores if sub_scores[t]["obv_bonus"] == 1.5)
    confirm = sum(1 for t in sub_scores if sub_scores[t]["obv_bonus"] == 0.5)
    bear_div = sum(1 for t in sub_scores if sub_scores[t]["obv_bonus"] == -1.0)
    print(f"  No OBV signal:       {no_prev} ({no_prev/len(sub_scores)*100:.1f}%)")
    print(f"  Confirming uptrend:  {confirm} ({confirm/len(sub_scores)*100:.1f}%)")
    print(f"  Bullish divergence:  {bull_div} ({bull_div/len(sub_scores)*100:.1f}%)")
    print(f"  Bearish divergence:  {bear_div} ({bear_div/len(sub_scores)*100:.1f}%)")


if __name__ == "__main__":
    all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w, vix_level = compute_all_scores()
    run_supplemental_analysis(all_scores, sub_scores, indicator_data, ai_recs, regime_name, regime_mom_w, regime_rev_w, vix_level)
