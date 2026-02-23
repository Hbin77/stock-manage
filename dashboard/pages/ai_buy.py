"""
AI 매수 추천 페이지
오늘의 추천 + 이력/정확도를 표시합니다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px

from analysis.ai_analyzer import ai_analyzer
from analysis.backtester import backtester
from config.settings import settings

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
    if "NASDAQ100" in indices:
        badges.append("`NASDAQ100`")
    if "SP500" in indices:
        badges.append("`S&P500`")
    if "ETF" in indices:
        badges.append("`ETF`")
    if "MIDCAP" in indices:
        badges.append("`MIDCAP`")
    if "SMALLCAP" in indices:
        badges.append("`SMALLCAP`")
    return " ".join(badges)


@st.cache_data(ttl=60)
def _get_todays_recs():
    return ai_analyzer.get_todays_recommendations()


@st.cache_data(ttl=300)
def _get_history(days: int):
    return ai_analyzer.get_recommendation_history(days=days)


@st.cache_data(ttl=3600)
def _get_accuracy_stats(days: int):
    return backtester.get_accuracy_stats(days=days)


@st.cache_data(ttl=3600)
def _get_action_breakdown(days: int):
    return backtester.get_action_breakdown(days=days)


@st.cache_data(ttl=3600)
def _get_monthly_perf(months: int):
    return backtester.get_monthly_performance(months=months)


def render():
    st.header("🤖 AI 매수 추천")

    # ── 오늘의 추천 ──────────────────────────────────────────────────────────
    st.subheader("오늘의 추천")
    recs = _get_todays_recs()

    # 분석 실행 버튼 (항상 표시)
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
        with st.spinner("AI 분석 중... (우선순위 종목 선별 후 분석, 1~3분 소요)"):
            try:
                ai_analyzer.analyze_all_watchlist()
                st.cache_data.clear()
                st.success("분석 완료!")
                st.rerun()
            except Exception as e:
                st.error(f"분석 실패: {e}")

    if not recs:
        st.info("오늘의 AI 분석 결과가 없습니다. 위 버튼으로 분석을 실행하세요.")
    else:
        # ── 인덱스 그룹 필터 탭 ──────────────────────────────────────────────
        if _HAS_TICKER_INDEX:
            tab_all, tab_nasdaq, tab_sp500, tab_etf, tab_midcap, tab_smallcap = st.tabs(
                ["전체", "NASDAQ100", "S&P500", "ETF", "MIDCAP", "SMALLCAP"]
            )
        else:
            tab_all = st.container()
            tab_nasdaq = tab_sp500 = tab_etf = tab_midcap = tab_smallcap = None

        def _render_recs(filtered_recs: list[dict]):
            buy_recs = [r for r in filtered_recs if r["action"] in ("BUY", "STRONG_BUY")]
            hold_recs = [r for r in filtered_recs if r["action"] == "HOLD"]

            if buy_recs:
                st.markdown(f"**매수 추천: {len(buy_recs)}개** | HOLD: {len(hold_recs)}개")
            else:
                st.markdown(f"**매수 추천 없음** | HOLD: {len(hold_recs)}개")

            # 매수 추천 카드
            for r in buy_recs:
                action_icon = "🟢🟢" if r["action"] == "STRONG_BUY" else "🟢"
                confidence_pct = int(r["confidence"] * 100)
                badges = _get_index_badges(r["ticker"])

                with st.expander(
                    f"{action_icon} **{r['ticker']}** — {r['action']} ({confidence_pct}%)  {badges}",
                    expanded=True,
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.metric("현재가", f"${r['price_at_recommendation']:.2f}" if r.get("price_at_recommendation") else "N/A")
                    c2.metric("목표가", f"${r['target_price']:.2f}" if r.get("target_price") else "N/A")
                    c3.metric("손절가", f"${r['stop_loss']:.2f}" if r.get("stop_loss") else "N/A")

                    c4, c5, c6 = st.columns(3)
                    c4.metric("기술점수", f"{r['technical_score']:.1f}/10" if r.get("technical_score") else "N/A")
                    c5.metric("펀더멘털", f"{r['fundamental_score']:.1f}/10" if r.get("fundamental_score") else "N/A")
                    c6.metric("심리점수", f"{r['sentiment_score']:.1f}/10" if r.get("sentiment_score") else "N/A")

                    st.markdown(f"**AI 분석:** {r['reasoning']}")
                    st.caption(f"분석 시각: {r['recommendation_date']}")

            # HOLD 종목 간략 표시
            if hold_recs:
                with st.expander(f"⏸ HOLD 종목 ({len(hold_recs)}개)", expanded=False):
                    for r in hold_recs:
                        badges = _get_index_badges(r["ticker"])
                        st.markdown(f"- **{r['ticker']}** {badges} ({int(r['confidence']*100)}%) — {r['reasoning'][:80]}...")

        with tab_all:
            _render_recs(recs)

        if _HAS_TICKER_INDEX and tab_nasdaq and tab_sp500:
            with tab_nasdaq:
                nasdaq_recs = [r for r in recs if "NASDAQ100" in TICKER_INDEX.get(r["ticker"], [])]
                if nasdaq_recs:
                    _render_recs(nasdaq_recs)
                else:
                    st.info("NASDAQ100 종목 추천 없음")

            with tab_sp500:
                sp500_recs = [r for r in recs if "SP500" in TICKER_INDEX.get(r["ticker"], [])]
                if sp500_recs:
                    _render_recs(sp500_recs)
                else:
                    st.info("S&P500 종목 추천 없음")

        if _HAS_TICKER_INDEX and tab_etf:
            with tab_etf:
                etf_recs = [r for r in recs if "ETF" in TICKER_INDEX.get(r["ticker"], [])]
                if etf_recs:
                    _render_recs(etf_recs)
                else:
                    st.info("ETF 추천 없음")

        if _HAS_TICKER_INDEX and tab_midcap:
            with tab_midcap:
                midcap_recs = [r for r in recs if "MIDCAP" in TICKER_INDEX.get(r["ticker"], [])]
                if midcap_recs:
                    _render_recs(midcap_recs)
                else:
                    st.info("MidCap 추천 없음")

        if _HAS_TICKER_INDEX and tab_smallcap:
            with tab_smallcap:
                smallcap_recs = [r for r in recs if "SMALLCAP" in TICKER_INDEX.get(r["ticker"], [])]
                if smallcap_recs:
                    _render_recs(smallcap_recs)
                else:
                    st.info("SmallCap 추천 없음")

    st.divider()

    # ── 추천 이력 ─────────────────────────────────────────────────────────────
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
            history = [h for h in history if h["action"] in action_filter]

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
                accuracy = len(profitable) / len(executed) * 100 if len(executed) > 0 else 0
                avg_return = executed["outcome_return"].mean()

                acc_col1, acc_col2, acc_col3 = st.columns(3)
                acc_col1.metric("실행된 추천", f"{len(executed)}건")
                acc_col2.metric("성공률", f"{accuracy:.1f}%")
                acc_col3.metric("평균 수익률", f"{avg_return:+.2f}%" if not pd.isna(avg_return) else "N/A")

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
                page_df.style.format(format_dict),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("선택한 필터에 해당하는 데이터가 없습니다.")

    st.divider()

    # ── AI 성과 분석 ───────────────────────────────────────────────────────────
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
            help="AI 추천 이후 실제 주가 변동을 조회하여 각 추천의 수익률(outcome_return)과 성공 여부를 DB에 기록합니다. 백테스팅 통계가 갱신됩니다.",
        ):
            with st.spinner("백테스팅 결과 계산 중..."):
                try:
                    n = backtester.update_outcomes()
                    st.cache_data.clear()
                    st.success(f"{n}건 업데이트 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"업데이트 실패: {e}")

    stats = _get_accuracy_stats(perf_days)

    # 5개 핵심 메트릭
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("전체 추천", f"{stats.get('total_recommendations', 0)}건")
    m2.metric("결과 집계", f"{stats.get('with_outcomes', 0)}건")

    win_rate = stats.get("win_rate")
    m3.metric("승률", f"{win_rate:.1f}%" if win_rate is not None else "N/A")

    avg_ret = stats.get("avg_return")
    _avg_ret_delta_color = "inverse" if (avg_ret is not None and avg_ret < 0) else "normal"
    m4.metric(
        "평균 수익률",
        f"{avg_ret:+.2f}%" if avg_ret is not None else "N/A",
        delta_color=_avg_ret_delta_color,
    )

    best_ticker = stats.get("best_ticker")
    best_ret = stats.get("best_return")
    m5.metric(
        "최고 수익 종목",
        best_ticker or "N/A",
        delta=f"{best_ret:+.2f}%" if best_ret is not None else None,
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

            # 액션별 상세 테이블
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
            if worst_ticker:
                st.caption(f"최저 수익: {worst_ticker} ({worst_ret:+.2f}%)" if worst_ret is not None else "")
