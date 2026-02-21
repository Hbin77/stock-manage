"""
포트폴리오 현황 페이지
보유 종목 테이블 + 투자 비중 파이차트 + 거래 입력 폼 + 알림 설정 + 성과 분석
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from notifications.alert_manager import alert_manager
from portfolio.portfolio_manager import portfolio_manager


# ── 캐시 함수 ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def _get_portfolio_data():
    return portfolio_manager.get_summary()


@st.cache_data(ttl=60)
def _get_alert_history():
    return alert_manager.get_alert_history(days=7)


@st.cache_data(ttl=300)
def _get_transaction_history(days: int):
    return portfolio_manager.get_transaction_history(days=days)


@st.cache_data(ttl=300)
def _get_realized_pnl():
    return portfolio_manager.get_realized_pnl_by_period()


@st.cache_data(ttl=300)
def _get_sector_allocation():
    return portfolio_manager.get_sector_allocation()


def _style_alert_row(row: pd.Series) -> list[str]:
    """알림 유형에 따라 행 배경색을 반환합니다."""
    alert_type = row.get("유형", "")
    if alert_type == "STOP_LOSS":
        return ["background-color: rgba(255, 68, 68, 0.25); color: #ff4444"] * len(row)
    if alert_type == "TARGET_PRICE":
        return ["background-color: rgba(0, 204, 68, 0.20); color: #00cc44"] * len(row)
    return [""] * len(row)


# ── 메인 렌더 ─────────────────────────────────────────────────────────────────

def render():
    st.header("💼 포트폴리오 현황")

    summary = _get_portfolio_data()
    holdings = summary.get("holdings", [])

    # ── 1. 상단 메트릭 5개 ───────────────────────────────────────────────────
    realized_data = _get_realized_pnl()
    total_realized = realized_data.get("total_realized", 0.0)

    col1, col2, col3, col4, col5 = st.columns(5)
    total_pnl = summary.get("total_unrealized_pnl", 0)
    total_pnl_pct = summary.get("total_unrealized_pnl_pct", 0)
    pnl_delta = f"{total_pnl_pct:+.2f}%"

    col1.metric("보유 종목 수", f"{summary.get('total_holdings', 0)}개")
    col2.metric("총 투자금액", f"${summary.get('total_invested', 0):,.0f}")
    col3.metric("현재 평가금액", f"${summary.get('total_value', 0):,.0f}")
    col4.metric("평가 손익", f"${total_pnl:+,.0f}", delta=pnl_delta, delta_color="normal")
    col5.metric("실현손익 누적", f"${total_realized:+,.0f}", delta_color="normal")

    st.divider()

    # ── 2. 보유 종목 테이블 + 파이차트 ──────────────────────────────────────
    if holdings:
        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.subheader("보유 종목 상세")
            df = pd.DataFrame(holdings)
            display_df = df[[
                "ticker", "name", "quantity", "avg_buy_price",
                "current_price", "current_value", "unrealized_pnl", "unrealized_pnl_pct",
                "first_bought_at",
            ]].copy()
            display_df.columns = [
                "티커", "종목명", "수량", "평균매수가",
                "현재가", "평가금액", "평가손익($)", "수익률(%)", "매수일",
            ]
            st.dataframe(
                display_df.style
                .format({
                    "수량": "{:.2f}",
                    "평균매수가": "${:.2f}",
                    "현재가": "${:.2f}",
                    "평가금액": "${:,.0f}",
                    "평가손익($)": "${:+,.2f}",
                    "수익률(%)": "{:+.2f}%",
                })
                .background_gradient(subset=["수익률(%)"], cmap="RdYlGn", vmin=-20, vmax=20),
                use_container_width=True,
                hide_index=True,
            )

        with col_right:
            st.subheader("투자 비중")
            pie_df = pd.DataFrame({
                "ticker": [h["ticker"] for h in holdings],
                "value": [h["current_value"] for h in holdings],
            })
            fig = px.pie(
                pie_df, names="ticker", values="value",
                template="plotly_dark", hole=0.4,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(showlegend=True, margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)

        st.caption("열 머리글을 클릭하면 해당 열 기준으로 오름차순/내림차순 정렬이 됩니다.")
        st.caption(f"기준 시각: {summary.get('updated_at', 'N/A')}")
    else:
        st.info("보유 종목이 없습니다.")

    st.divider()

    # ── 3. 거래 입력 폼 ──────────────────────────────────────────────────────
    st.subheader("📝 거래 입력")
    buy_tab, sell_tab = st.tabs(["매수", "매도"])

    with buy_tab:
        with st.form("buy_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            ticker_buy = fc1.text_input("티커", placeholder="예: AAPL").strip().upper()
            quantity_buy = fc2.number_input("수량", min_value=0.0001, step=0.0001, format="%.4f")

            fc3, fc4, fc5 = st.columns(3)
            price_buy = fc3.number_input("매수 단가 ($)", min_value=0.01, step=0.01, format="%.2f")
            fee_buy = fc4.number_input("수수료 ($)", min_value=0.0, step=0.01, format="%.2f", value=0.0)
            date_buy = fc5.date_input("체결일", value=date.today())

            note_buy = st.text_input("메모 (선택)", placeholder="AI 추천 근거 등")
            submitted_buy = st.form_submit_button("매수 등록", type="primary")

        if submitted_buy:
            if not ticker_buy:
                st.error("티커를 입력하세요.")
            elif quantity_buy <= 0 or price_buy <= 0:
                st.error("수량과 가격은 0보다 커야 합니다.")
            else:
                try:
                    executed_at = datetime.combine(date_buy, datetime.min.time())
                    portfolio_manager.buy(
                        ticker=ticker_buy,
                        quantity=quantity_buy,
                        price=price_buy,
                        fee=fee_buy,
                        note=note_buy or None,
                        executed_at=executed_at,
                    )
                    st.toast(f"{ticker_buy} {quantity_buy}주 @ ${price_buy:.2f} 매수 등록 완료!", icon="✅")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.toast(f"매수 실패: {e}", icon="❌")

    with sell_tab:
        if not holdings:
            st.info("보유 종목이 없습니다.")
        else:
            holding_options = {h["ticker"]: h for h in holdings}
            selected_ticker = st.selectbox("종목 선택", list(holding_options.keys()), key="sell_ticker")
            selected_holding = holding_options[selected_ticker]

            info_c1, info_c2 = st.columns(2)
            info_c1.metric("보유 수량", f"{selected_holding['quantity']:.4f}주")
            info_c2.metric("평균 매수가", f"${selected_holding['avg_buy_price']:.2f}")

            with st.form("sell_form", clear_on_submit=True):
                fs1, fs2, fs3 = st.columns(3)
                quantity_sell = fs1.number_input(
                    "매도 수량",
                    min_value=0.0001,
                    max_value=float(selected_holding["quantity"]),
                    step=0.0001,
                    format="%.4f",
                    value=float(selected_holding["quantity"]),
                )
                price_sell = fs2.number_input("매도 단가 ($)", min_value=0.01, step=0.01, format="%.2f",
                                               value=float(selected_holding.get("current_price") or selected_holding["avg_buy_price"]))
                fee_sell = fs3.number_input("수수료 ($)", min_value=0.0, step=0.01, format="%.2f", value=0.0)
                date_sell = st.date_input("체결일", value=date.today(), key="sell_date")
                note_sell = st.text_input("메모 (선택)", key="sell_note")

                # 실현손익 미리보기
                preview_pnl = (quantity_sell * price_sell - fee_sell) - (selected_holding["avg_buy_price"] * quantity_sell)
                st.info(f"예상 실현손익: **${preview_pnl:+,.2f}**")

                submitted_sell = st.form_submit_button("매도 등록", type="primary")

            if submitted_sell:
                try:
                    executed_at = datetime.combine(date_sell, datetime.min.time())
                    portfolio_manager.sell(
                        ticker=selected_ticker,
                        quantity=quantity_sell,
                        price=price_sell,
                        fee=fee_sell,
                        note=note_sell or None,
                        executed_at=executed_at,
                    )
                    st.toast(
                        f"{selected_ticker} {quantity_sell}주 @ ${price_sell:.2f} 매도 완료! 실현손익 ${preview_pnl:+,.2f}",
                        icon="✅",
                    )
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.toast(f"매도 실패: {e}", icon="❌")

    st.divider()

    # ── 4. 알림 설정 ─────────────────────────────────────────────────────────
    st.subheader("🔔 알림 설정")

    if not holdings:
        st.info("보유 종목이 없어 알림을 설정할 수 없습니다.")
    else:
        with st.form("alert_form", clear_on_submit=True):
            alert_tickers = [h["ticker"] for h in holdings]
            fa1, fa2, fa3 = st.columns(3)
            alert_ticker = fa1.selectbox("종목", alert_tickers, key="alert_ticker_sel")
            alert_type = fa2.selectbox(
                "알림 유형",
                ["STOP_LOSS", "TARGET_PRICE", "VOLUME_SURGE"],
                format_func=lambda x: {"STOP_LOSS": "🔴 손절가", "TARGET_PRICE": "🎯 목표가", "VOLUME_SURGE": "📊 거래량 급등"}.get(x, x),
            )
            threshold_val = fa3.number_input(
                "기준값 (가격 또는 배수)",
                min_value=0.01,
                step=0.01,
                format="%.2f",
                help="STOP_LOSS/TARGET_PRICE: 달러 가격 | VOLUME_SURGE: 평균 대비 배수 (예: 3.0)",
            )
            submitted_alert = st.form_submit_button("알림 설정 저장")

        if submitted_alert:
            ok = alert_manager.set_alert(alert_ticker, alert_type, threshold_val)
            if ok:
                st.success(f"✅ {alert_ticker} {alert_type} 알림 설정 완료 (기준: {threshold_val})")
            else:
                st.error("알림 설정 실패. 로그를 확인하세요.")

    st.divider()

    # ── 5. 알림 이력 ─────────────────────────────────────────────────────────
    st.subheader("📋 최근 알림 이력 (7일)")
    alert_hist = _get_alert_history()

    if not alert_hist:
        st.info("최근 7일간 발화된 알림이 없습니다.")
    else:
        ah_df = pd.DataFrame(alert_hist)
        ah_display = ah_df[["triggered_at", "ticker", "alert_type", "trigger_price", "message", "is_sent"]].copy()
        ah_display.columns = ["발화시각", "티커", "유형", "발화가($)", "메시지", "전송"]
        st.dataframe(
            ah_display.style.apply(_style_alert_row, axis=1),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("행 색상: 🔴 빨강 = STOP_LOSS(손절 발화) | 🟢 초록 = TARGET_PRICE(목표가 달성)")

    st.divider()

    # ── 6. 성과 분석 탭 ──────────────────────────────────────────────────────
    st.subheader("📈 성과 분석")
    tab_history, tab_chart = st.tabs(["거래 이력", "성과 차트"])

    with tab_history:
        tx_days = st.selectbox(
            "조회 기간",
            [30, 90, 180, 365],
            index=3,
            key="tx_days",
            format_func=lambda d: f"최근 {d}일",
        )
        tx_history = _get_transaction_history(tx_days)
        if not tx_history:
            st.info("거래 내역이 없습니다.")
        else:
            tx_df = pd.DataFrame(tx_history)
            tx_display = tx_df[[
                "executed_at", "ticker", "name", "action",
                "quantity", "price", "total_amount", "fee", "realized_pnl", "note",
            ]].copy()
            tx_display.columns = [
                "체결일시", "티커", "종목명", "구분",
                "수량", "단가($)", "총액($)", "수수료($)", "실현손익($)", "메모",
            ]
            st.dataframe(
                tx_display.style.format({
                    "수량": "{:.4f}",
                    "단가($)": "${:.2f}",
                    "총액($)": "${:,.2f}",
                    "수수료($)": "${:.2f}",
                    "실현손익($)": lambda x: f"${x:+,.2f}" if pd.notna(x) else "-",
                }),
                use_container_width=True,
                hide_index=True,
            )

    with tab_chart:
        realized_data = _get_realized_pnl()
        sector_data = _get_sector_allocation()

        ch1, ch2 = st.columns(2)

        with ch1:
            st.markdown("**월별 실현손익**")
            monthly = realized_data.get("monthly", [])
            if monthly:
                mo_df = pd.DataFrame(monthly)
                fig_pnl = px.bar(
                    mo_df,
                    x="month",
                    y="realized_pnl",
                    color="realized_pnl",
                    color_continuous_scale=["#ff4444", "#ffaa00", "#00cc44"],
                    text=mo_df["realized_pnl"].apply(lambda x: f"${x:+,.0f}"),
                    labels={"month": "월", "realized_pnl": "실현손익($)"},
                    template="plotly_dark",
                )
                fig_pnl.update_traces(textposition="outside")
                fig_pnl.update_layout(
                    coloraxis_showscale=False,
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=350,
                )
                st.plotly_chart(fig_pnl, use_container_width=True)
                st.metric(
                    "총 실현손익",
                    f"${realized_data.get('total_realized', 0):+,.2f}",
                    delta_color="normal",
                )
            else:
                st.info("실현손익 데이터가 없습니다.")

        with ch2:
            st.markdown("**섹터 비중**")
            if sector_data:
                sec_df = pd.DataFrame(sector_data)
                fig_sec = px.pie(
                    sec_df,
                    names="sector",
                    values="value",
                    template="plotly_dark",
                    hole=0.35,
                )
                fig_sec.update_traces(textposition="inside", textinfo="percent+label")
                fig_sec.update_layout(
                    showlegend=True,
                    margin=dict(t=20, b=20, l=20, r=20),
                    height=350,
                )
                st.plotly_chart(fig_sec, use_container_width=True)

                # 섹터 상세 테이블
                sec_display = sec_df.rename(columns={"sector": "섹터", "value": "평가금액($)", "pct": "비중(%)"})
                st.dataframe(
                    sec_display.style.format({"평가금액($)": "${:,.0f}", "비중(%)": "{:.1f}%"}),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("보유 종목이 없습니다.")
