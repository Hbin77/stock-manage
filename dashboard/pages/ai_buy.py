"""
AI 매수 추천 페이지
오늘의 추천 + 이력/정확도를 표시합니다.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px

from analysis.ai_analyzer import ai_analyzer
from analysis.backtester import backtester
from config.settings import settings
from database.connection import get_db
from database.models import Stock
from dashboard.utils import (
    safe_call, safe_div, fmt_dollar, fmt_pct, fmt_score, fmt_count,
    clear_analysis_cache,
    CACHE_TTL_REALTIME, CACHE_TTL_MEDIUM, CACHE_TTL_LONG,
    score_label, confidence_label, fmt_upside, html_score_bar,
    action_badge_html, value_color,
)

try:
    from config.tickers import TICKER_INDEX
    _HAS_TICKER_INDEX = True
except ImportError:
    _HAS_TICKER_INDEX = False


def _get_index_badges(ticker: str) -> str:
    """티커의 인덱스 배지 문자열 반환"""
    if not _HAS_TICKER_INDEX:
        return ""
    indices = TICKER_INDEX.get(ticker, [])
    badges = []
    for idx in ("NASDAQ100", "SP500", "ETF", "MIDCAP", "SMALLCAP"):
        if idx in indices:
            badges.append(f"`{idx}`")
    return " ".join(badges)


# ── 캐시 함수 ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL_REALTIME)
def _get_todays_recs():
    return safe_call(ai_analyzer.get_todays_recommendations, default=[])


@st.cache_data(ttl=CACHE_TTL_MEDIUM)
def _get_history(days: int):
    return safe_call(ai_analyzer.get_recommendation_history, days, default=[])


@st.cache_data(ttl=CACHE_TTL_LONG)
def _get_accuracy_stats(days: int):
    return safe_call(backtester.get_accuracy_stats, days, default={})


@st.cache_data(ttl=CACHE_TTL_LONG)
def _get_action_breakdown(days: int):
    return safe_call(backtester.get_action_breakdown, days, default=[])


@st.cache_data(ttl=CACHE_TTL_LONG)
def _get_monthly_perf(months: int):
    return safe_call(backtester.get_monthly_performance, months, default=[])


@st.cache_data(ttl=CACHE_TTL_REALTIME)
def _get_top_picks():
    return safe_call(ai_analyzer.get_top_picks, 3, default=[])


# ── 메인 렌더 ──────────────────────────────────────────────────────────────

def render():
    st.header("🤖 AI 매수 추천")

    # ── Top 3 최종 추천 ─────────────────────────────────────────────────
    top_picks = _get_top_picks()
    recs_exist = bool(_get_todays_recs())

    if top_picks:
        has_buy = any(p["action"] in ("BUY", "STRONG_BUY") for p in top_picks)
        if has_buy:
            st.subheader("Top 3 매수 추천")
        else:
            st.subheader("Top 3 유망 종목")
            st.caption("현재 BUY 추천이 없어 HOLD 종목 중 가장 유망한 3개를 표시합니다")

        medal_map = {1: "🥇", 2: "🥈", 3: "🥉"}
        cols = st.columns(min(len(top_picks), 3))
        for i, pick in enumerate(top_picks):
            with cols[i]:
                medal = medal_map.get(pick.get("rank", i + 1), "")
                action = pick.get("action", "HOLD")
                action_class = {
                    "STRONG_BUY": "strong-buy", "BUY": "buy",
                }.get(action, "hold")

                price_at = pick.get("price_at_recommendation") or 0
                target = pick.get("target_price") or 0
                upside_str = fmt_upside(price_at, target)
                upside_pct = safe_div(target - price_at, price_at) * 100 if price_at > 0 else 0.0
                upside_cls = "upside-positive" if upside_pct >= 0 else "upside-negative"

                confidence_val = pick.get("confidence") or 0
                conf_pct = int(confidence_val * 100)
                conf_lbl = confidence_label(confidence_val)
                rr = pick.get("risk_reward_ratio", 0) or 0

                ts = pick.get("technical_score")
                fs = pick.get("fundamental_score")
                ss = pick.get("sentiment_score")
                cs = pick.get("composite_score")

                card_html = f"""
                <div class="top-pick-card {action_class}">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                        <span style="font-size:1.2rem;font-weight:700;color:#e6edf3;">
                            {medal} #{pick.get('rank', i+1)} {pick['ticker']}
                        </span>
                        {action_badge_html(action)}
                    </div>
                    <div style="font-size:0.8rem;color:#8b949e;margin-bottom:10px;">
                        {pick.get('name', '')}
                    </div>
                    <div style="margin-bottom:10px;text-align:center;">
                        <span class="upside-badge {upside_cls}">{upside_str}</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:0.8rem;color:#8b949e;margin-bottom:8px;">
                        <span>현재가 <b style="color:#e6edf3">{fmt_dollar(price_at)}</b></span>
                        <span>목표가 <b style="color:#23c55e">{fmt_dollar(target)}</b></span>
                    </div>
                    <div style="display:flex;justify-content:space-between;font-size:0.78rem;color:#8b949e;margin-bottom:12px;">
                        <span>신뢰도 <b style="color:#e6edf3">{conf_pct}%</b> ({conf_lbl})</span>
                        <span>R/R <b style="color:#e6edf3">{rr:.2f}</b></span>
                    </div>
                    {html_score_bar(ts, 10, "#58a6ff", "기술")}
                    {html_score_bar(fs, 10, "#23c55e", "펀더멘탈")}
                    {html_score_bar(ss, 10, "#eab308", "심리")}
                    {html_score_bar(cs, 10, "#a78bfa", "종합")}
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)

                with st.expander("AI 분석 근거", expanded=False):
                    st.markdown(pick.get("reasoning") or "분석 근거 없음")

        st.divider()
    elif recs_exist:
        st.subheader("Top 3 매수 추천")
        st.info("오늘의 분석 결과가 없습니다. AI 분석을 실행하세요.")
        st.divider()

    # ── 오늘의 추천 ──────────────────────────────────────────────────────
    st.subheader("오늘의 추천")
    recs = _get_todays_recs()

    # ── 분석 실행 버튼 (CRITICAL FIX) ────────────────────────────────────
    btn_col, info_col = st.columns([1, 3])
    with btn_col:
        run_analysis = st.button("🔍 AI 분석 실행", type="primary")
    with info_col:
        total_watchlist = len(settings.WATCHLIST_TICKERS)
        if total_watchlist > 50:
            st.caption(f"{total_watchlist}개 종목 중 기술적 조건 상위 50개 분석")
        if recs:
            st.caption(f"마지막 분석: {recs[0].get('recommendation_date', 'N/A')}")

    if run_analysis:
        progress = st.progress(0, text="분석 준비 중...")
        try:
            progress.progress(10, text="AI 분석 중... (약 1-2분)")
            results = ai_analyzer.analyze_all_watchlist()
            buy_count = sum(1 for a in results.values() if a in ("BUY", "STRONG_BUY"))
            progress.progress(100, text="완료!")
            st.toast(f"분석 완료! BUY {buy_count}건 / 전체 {len(results)}건")
            clear_analysis_cache()
            time.sleep(0.5)
            st.rerun()
        except Exception as e:
            progress.empty()
            st.error(f"분석 실패: {e}")

    if not recs:
        st.info("오늘의 AI 분석 결과가 없습니다. 위 버튼으로 분석을 실행하세요.")
    else:
        # ── 인덱스 필터 (selectbox) ─────────────────────────────────────
        index_options = ["전체"]
        if _HAS_TICKER_INDEX:
            index_options += ["NASDAQ100", "S&P500", "MIDCAP", "SMALLCAP"]
        selected_index = st.selectbox("인덱스 필터", index_options, key="index_filter")

        # 선택된 인덱스로 필터링
        if selected_index == "전체" or not _HAS_TICKER_INDEX:
            filtered_recs = recs
        else:
            idx_key = "SP500" if selected_index == "S&P500" else selected_index
            filtered_recs = [
                r for r in recs
                if idx_key in TICKER_INDEX.get(r["ticker"], [])
            ]

        def _render_recs(filtered_recs: list[dict]):
            buy_recs = [r for r in filtered_recs if r["action"] in ("BUY", "STRONG_BUY")]
            hold_recs = [r for r in filtered_recs if r["action"] == "HOLD"]

            if buy_recs:
                st.markdown(f"**매수 추천: {len(buy_recs)}개** | HOLD: {len(hold_recs)}개")
            else:
                st.markdown(f"**매수 추천 없음** | HOLD: {len(hold_recs)}개")

            for r in buy_recs:
                confidence_pct = int((r.get("confidence") or 0) * 100)
                badges = _get_index_badges(r["ticker"])

                ts = r.get("technical_score") or 0.0
                fs = r.get("fundamental_score") or 0.0
                ss = r.get("sentiment_score") or 0.0
                w_score = r.get("weighted_score") or (ts * 0.45 + fs * 0.30 + ss * 0.25)

                price_at = r.get("price_at_recommendation") or 0
                target_p = r.get("target_price") or 0
                stop_loss_p = r.get("stop_loss") or 0

                upside_pct = safe_div(target_p - price_at, price_at) * 100 if price_at > 0 else 0.0
                downside_pct = safe_div(stop_loss_p - price_at, price_at) * 100 if price_at > 0 else 0.0
                rr_ratio = abs(safe_div(upside_pct, downside_pct)) if downside_pct != 0 else 0.0

                # 3-pillar formula string
                pillar_str = (
                    f"기술({ts:.1f})*0.45 + 펀더({fs:.1f})*0.30 + 심리({ss:.1f})*0.25 = {w_score:.2f}"
                )
                # upside/downside/R:R string
                updown_str = (
                    f"목표 {'+' if upside_pct >= 0 else ''}{upside_pct:.1f}% | "
                    f"손절 {downside_pct:.1f}% | R/R {rr_ratio:.2f}"
                )

                with st.expander(
                    f"{action_badge_html(r['action'])}  **{r['ticker']}** ({confidence_pct}%)  {badges}",
                    expanded=True,
                ):
                    c1, c2, c3, c0 = st.columns(4)
                    c1.metric("현재가", fmt_dollar(price_at))
                    c2.metric("목표가", fmt_dollar(target_p))
                    c3.metric("손절가", fmt_dollar(stop_loss_p))
                    c0.metric("가중점수", f"{w_score:.2f}/10")

                    # 3-pillar score bars
                    pillar_html = f"""
                    <div style="margin:8px 0;">
                        {html_score_bar(ts, 10, "#58a6ff", "기술(x0.45)")}
                        {html_score_bar(fs, 10, "#23c55e", "펀더(x0.30)")}
                        {html_score_bar(ss, 10, "#eab308", "심리(x0.25)")}
                    </div>
                    <div style="font-size:0.78rem;color:#8b949e;font-family:'JetBrains Mono',monospace;margin:4px 0;">
                        {pillar_str}
                    </div>
                    <div style="font-size:0.78rem;color:#c9d1d9;font-family:'JetBrains Mono',monospace;margin:4px 0;">
                        {updown_str}
                    </div>
                    """
                    st.markdown(pillar_html, unsafe_allow_html=True)

                    st.markdown(f"**AI 분석:** {r.get('reasoning', '')}")
                    st.caption(f"분석 시각: {r.get('recommendation_date', 'N/A')}")

            if hold_recs:
                with st.expander(f"HOLD 종목 ({len(hold_recs)}개)", expanded=False):
                    for r in hold_recs:
                        badges = _get_index_badges(r["ticker"])
                        reasoning = (r.get("reasoning") or "")[:80]
                        conf = int((r.get("confidence") or 0) * 100)
                        st.markdown(f"- **{r['ticker']}** {badges} ({conf}%) -- {reasoning}...")

        st.caption("개별 주식만 분석됩니다 (ETF 제외)")
        if filtered_recs:
            _render_recs(filtered_recs)
        else:
            st.info(f"{selected_index} 종목 추천 없음")

        # ── 섹터 분포 ────────────────────────────────────────────────────
        tickers_in_recs = [r["ticker"] for r in recs]
        if tickers_in_recs:
            try:
                with get_db() as db:
                    stocks = db.query(Stock.ticker, Stock.sector).filter(
                        Stock.ticker.in_(tickers_in_recs)
                    ).all()
                    sector_map = {s.ticker: (s.sector or "Unknown") for s in stocks}
            except Exception:
                sector_map = {}

            sector_counts: dict[str, int] = {}
            for t in tickers_in_recs:
                sec = sector_map.get(t, "Unknown")
                sector_counts[sec] = sector_counts.get(sec, 0) + 1

            if sector_counts:
                st.subheader("섹터 분포")
                sec_df = pd.DataFrame(
                    [{"섹터": k, "종목수": v} for k, v in sorted(sector_counts.items(), key=lambda x: -x[1])]
                )
                fig_sec = px.pie(
                    sec_df, names="섹터", values="종목수",
                    template="plotly_dark",
                    hole=0.4,
                )
                fig_sec.update_layout(
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=350,
                )
                st.plotly_chart(fig_sec, use_container_width=True)

    st.divider()

    # ── 추천 이력 ──────────────────────────────────────────────────────────
    st.subheader("추천 이력")

    col1, col2 = st.columns([2, 1])
    with col1:
        days = st.selectbox("조회 기간", [7, 14, 30, 90], index=2, key="ai_buy_days",
                            format_func=lambda d: f"최근 {d}일")
    with col2:
        action_filter = st.multiselect("필터", ["STRONG_BUY", "BUY", "HOLD"],
                                        default=["STRONG_BUY", "BUY"], key="ai_buy_filter")

    history = _get_history(days)

    if not history:
        st.info("이력 데이터가 없습니다.")
    else:
        if action_filter:
            history = [h for h in history if h.get("action") in action_filter]

        df = pd.DataFrame(history)
        if not df.empty:
            display_cols = ["recommendation_date", "ticker", "action", "confidence",
                            "price_at_recommendation", "target_price", "stop_loss", "outcome_return"]
            available_cols = [c for c in display_cols if c in df.columns]
            display_df = df[available_cols].copy()

            col_rename = {
                "recommendation_date": "일시",
                "ticker": "티커",
                "action": "추천",
                "confidence": "신뢰도",
                "price_at_recommendation": "추천가($)",
                "target_price": "목표가($)",
                "stop_loss": "손절가($)",
                "outcome_return": "결과(%)",
            }
            display_df.rename(columns=col_rename, inplace=True)

            # 정확도 지표
            executed = df[df["is_executed"] == True] if "is_executed" in df.columns else pd.DataFrame()
            if not executed.empty and "outcome_return" in executed.columns:
                executed = executed.dropna(subset=["outcome_return"])
                profitable = executed[executed["outcome_return"] > 0]
                accuracy = safe_div(len(profitable), len(executed)) * 100
                avg_return = executed["outcome_return"].mean()

                acc_col1, acc_col2, acc_col3 = st.columns(3)
                acc_col1.metric("실행된 추천", fmt_count(len(executed)))
                acc_col2.metric("성공률", fmt_pct(accuracy, with_sign=False))
                acc_col3.metric("평균 수익률", fmt_pct(avg_return, decimals=2) if not pd.isna(avg_return) else "N/A")

            format_dict = {}
            if "신뢰도" in display_df.columns:
                format_dict["신뢰도"] = "{:.0%}"
            if "추천가($)" in display_df.columns:
                format_dict["추천가($)"] = "${:.2f}"
            if "목표가($)" in display_df.columns:
                format_dict["목표가($)"] = lambda x: f"${x:.2f}" if pd.notna(x) else "-"
            if "손절가($)" in display_df.columns:
                format_dict["손절가($)"] = lambda x: f"${x:.2f}" if pd.notna(x) else "-"
            if "결과(%)" in display_df.columns:
                format_dict["결과(%)"] = lambda x: f"{x:+.2f}%" if pd.notna(x) else "-"

            PAGE_SIZE = 50
            total_rows = len(display_df)
            if total_rows > PAGE_SIZE:
                total_pages = (total_rows + PAGE_SIZE - 1) // PAGE_SIZE
                page = st.number_input(
                    "페이지",
                    min_value=1,
                    max_value=total_pages,
                    value=1,
                    step=1,
                    key="ai_buy_page",
                )
                start_idx = (page - 1) * PAGE_SIZE
                end_idx = start_idx + PAGE_SIZE
                page_df = display_df.iloc[start_idx:end_idx]
                st.caption(f"{total_rows}건 중 {start_idx + 1}~{min(end_idx, total_rows)}건 표시 (총 {total_pages}페이지)")
            else:
                page_df = display_df

            st.dataframe(
                page_df.style.format(format_dict, na_rep="-"),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("선택한 필터에 해당하는 데이터가 없습니다.")

    st.divider()

    # ── AI 성과 분석 ──────────────────────────────────────────────────────
    st.subheader("📊 AI 성과 분석")

    perf_col1, perf_col2 = st.columns([2, 1])
    with perf_col1:
        perf_days = st.selectbox(
            "분석 기간",
            [30, 60, 90, 180],
            index=2,
            key="perf_days",
            format_func=lambda d: f"최근 {d}일",
        )
    with perf_col2:
        if st.button(
            "결과 업데이트",
            key="update_outcomes",
            help="AI 추천 이후 실제 주가 변동을 조회하여 수익률을 DB에 기록합니다.",
        ):
            with st.spinner("백테스팅 결과 계산 중..."):
                try:
                    n = backtester.update_outcomes()
                    clear_analysis_cache()
                    st.toast(f"{n}건 업데이트 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"업데이트 실패: {e}")

    stats = _get_accuracy_stats(perf_days)

    # 5개 핵심 메트릭
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("전체 추천", fmt_count(stats.get("total_recommendations", 0)))
    m2.metric("결과 집계", fmt_count(stats.get("with_outcomes", 0)))

    win_rate = stats.get("win_rate")
    m3.metric("승률", fmt_pct(win_rate, with_sign=False) if win_rate is not None else "N/A")

    avg_ret = stats.get("avg_return")
    m4.metric(
        "평균 수익률",
        fmt_pct(avg_ret, decimals=2) if avg_ret is not None else "N/A",
        delta_color="inverse" if (avg_ret is not None and avg_ret < 0) else "normal",
    )

    best_ticker = stats.get("best_ticker")
    best_ret = stats.get("best_return")
    m5.metric(
        "최고 수익 종목",
        best_ticker or "N/A",
        delta=fmt_pct(best_ret, decimals=2) if best_ret is not None else None,
        delta_color="normal",
    )

    # 2열 Plotly 차트
    breakdown = _get_action_breakdown(perf_days)
    monthly = _get_monthly_perf(6)

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.markdown("**액션별 평균 수익률**")
        if breakdown:
            bd_df = pd.DataFrame(breakdown)
            fig_bd = px.bar(
                bd_df,
                x="action",
                y="avg_return",
                color="avg_return",
                color_continuous_scale=["#ff4444", "#ffaa00", "#00cc44"],
                text=bd_df["avg_return"].apply(lambda x: f"{x:+.2f}%"),
                labels={"action": "액션", "avg_return": "평균 수익률(%)"},
                template="plotly_dark",
            )
            fig_bd.update_traces(textposition="outside")
            fig_bd.update_layout(
                coloraxis_showscale=False,
                margin=dict(t=20, b=20, l=20, r=20),
                height=300,
            )
            st.plotly_chart(fig_bd, use_container_width=True)

            bd_display = pd.DataFrame(breakdown).rename(columns={
                "action": "액션", "count": "건수",
                "win_rate": "승률(%)", "avg_return": "평균수익률(%)",
            })
            st.dataframe(bd_display, use_container_width=True, hide_index=True)
        else:
            st.info("결과 데이터가 없습니다.")

    with chart_col2:
        st.markdown("**월별 평균 수익률**")
        if monthly:
            mo_df = pd.DataFrame(monthly)
            fig_mo = px.bar(
                mo_df,
                x="month",
                y="avg_return",
                color="avg_return",
                color_continuous_scale=["#ff4444", "#ffaa00", "#00cc44"],
                text=mo_df["avg_return"].apply(lambda x: f"{x:+.2f}%"),
                labels={"month": "월", "avg_return": "평균 수익률(%)"},
                template="plotly_dark",
            )
            fig_mo.update_traces(textposition="outside")
            fig_mo.update_layout(
                coloraxis_showscale=False,
                margin=dict(t=20, b=20, l=20, r=20),
                height=300,
            )
            st.plotly_chart(fig_mo, use_container_width=True)

            sharpe = stats.get("sharpe_proxy")
            worst_ticker = stats.get("worst_ticker")
            worst_ret = stats.get("worst_return")
            st.caption(
                f"Sharpe(근사): {sharpe:.3f}" if sharpe else "Sharpe: N/A"
            )
            if worst_ticker and worst_ret is not None:
                st.caption(f"최저 수익: {worst_ticker} ({worst_ret:+.2f}%)")
        else:
            st.info("월별 데이터가 없습니다.")
