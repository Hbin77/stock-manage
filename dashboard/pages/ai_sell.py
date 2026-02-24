"""
AI 매도 신호 페이지
보유 종목별 SELL/HOLD 상태를 표시합니다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from analysis.sell_analyzer import sell_analyzer
from portfolio.portfolio_manager import portfolio_manager


@st.cache_data(ttl=60)
def _get_sell_signals():
    return sell_analyzer.get_active_sell_signals()


@st.cache_data(ttl=60)
def _get_holdings():
    return portfolio_manager.get_holdings(update_prices=False)


def _render_score_bars(s: dict):
    """구조화 스코어(technical_score, position_risk_score, fundamental_score, sell_pressure)를 progress bar로 표시"""
    tech = s.get("technical_score")
    pos_risk = s.get("position_risk_score")
    fund = s.get("fundamental_score")
    sell_p = s.get("sell_pressure")

    has_scores = any(v is not None for v in [tech, pos_risk, fund, sell_p])
    if not has_scores:
        return

    st.markdown("**스코어 분석:**")
    cols = st.columns(4)

    score_items = [
        (cols[0], "기술적 악화", tech),
        (cols[1], "포지션 리스크", pos_risk),
        (cols[2], "펀더멘털/심리", fund),
        (cols[3], "매도 압력", sell_p),
    ]
    for col, label, val in score_items:
        if val is not None:
            col.caption(f"{label}: {val:.1f}/10")
            col.progress(min(val / 10.0, 1.0))
        else:
            col.caption(f"{label}: N/A")


def _render_exit_strategy(s: dict):
    """exit_strategy 정보가 있으면 표시"""
    exit_strat = s.get("exit_strategy")
    if not exit_strat:
        return

    strategy_labels = {
        "IMMEDIATE": ("즉시 매도", "🔴"),
        "LIMIT_SELL": ("지정가 매도", "🟠"),
        "SCALE_OUT": ("분할 매도", "🟡"),
        "HOLD_WITH_STOP": ("손절가 설정 후 보유", "🟢"),
    }
    label, icon = strategy_labels.get(exit_strat, (exit_strat, ""))
    st.markdown(f"**매도 전략:** {icon} {label}")


def _render_summary(signals: list[dict], total_holdings: int):
    """매도 종합 요약 섹션"""
    sell_count = sum(1 for s in signals if s["signal"] in ("SELL", "STRONG_SELL"))
    hold_count = sum(1 for s in signals if s["signal"] == "HOLD")
    confidences = [s["confidence"] for s in signals if s.get("confidence") is not None]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    st.subheader("매도 종합 요약")
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("전체 보유 종목", f"{total_holdings}개")
    mc2.metric("SELL 신호", f"{sell_count}개",
               delta=f"{sell_count}개 매도 권고" if sell_count > 0 else None,
               delta_color="inverse" if sell_count > 0 else "off")
    mc3.metric("평균 신뢰도", f"{avg_conf:.0%}")

    st.divider()


def render():
    st.header("📉 AI 매도 신호")

    holdings = _get_holdings()
    if not holdings:
        st.info("보유 종목이 없습니다.")
        return

    signals = _get_sell_signals()
    signal_map = {s["ticker"]: s for s in signals}

    # ── 매도 종합 요약 ────────────────────────────────────────────────────────
    if signals:
        _render_summary(signals, len(holdings))

    # ── 매도 신호 종목 (SELL/STRONG_SELL) ────────────────────────────────────
    sell_signals = [s for s in signals if s["signal"] in ("SELL", "STRONG_SELL")]

    if sell_signals:
        st.markdown(f"⚠️ **매도 신호 감지: {len(sell_signals)}개 종목**")
        for s in sell_signals:
            urgency_color = {"HIGH": "🔴", "NORMAL": "🟠", "LOW": "🟡"}.get(s["urgency"], "🟠")
            signal_icon = "📉📉" if s["signal"] == "STRONG_SELL" else "📉"
            pnl_pct = s.get("current_pnl_pct", 0) or 0

            with st.expander(
                f"{urgency_color}{signal_icon} **{s['ticker']}** — {s['signal']} "
                f"(수익률: {pnl_pct:+.1f}%, 신뢰도: {int(s['confidence']*100)}%)",
                expanded=True,
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("현재가", f"${s['current_price']:.2f}" if s.get("current_price") else "N/A")
                c2.metric("제안 매도가",
                          f"${s['suggested_sell_price']:.2f}" if s.get("suggested_sell_price") else "N/A")
                c3.metric("현재 수익률", f"{pnl_pct:+.1f}%",
                          delta_color="normal" if pnl_pct >= 0 else "inverse")

                _render_score_bars(s)
                _render_exit_strategy(s)

                col_u, col_s = st.columns(2)
                col_u.markdown(f"**긴급도:** {s['urgency']}")
                col_s.markdown(f"**신뢰도:** {int(s['confidence']*100)}%")

                st.markdown(f"**AI 분석:** {s['reasoning']}")
                st.caption(f"분석 시각: {s['signal_date']}")

    else:
        st.success("✅ 현재 매도 신호가 없습니다. 모든 보유 종목이 안정적입니다.")

    st.divider()

    # ── 전체 보유 종목 상태 ───────────────────────────────────────────────────
    st.subheader("보유 종목 전체 현황")

    if not signals:
        st.info("오늘의 매도 분석이 아직 실행되지 않았습니다.")
        if st.button("🔍 AI 매도 분석 실행", type="primary", key="sell_analyze_first"):
            with st.spinner("매도 신호 병렬 분석 중... (약 30초)"):
                try:
                    sell_analyzer.analyze_all_holdings()
                    st.cache_data.clear()
                    st.toast("분석 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"분석 실패: {e}")
        return

    for h in holdings:
        ticker = h["ticker"]
        sig = signal_map.get(ticker)

        if sig is None:
            status_icon = "⚪"
            status_text = "미분석"
            expanded = False
        elif sig["signal"] in ("SELL", "STRONG_SELL"):
            status_icon = "🔴"
            status_text = sig["signal"]
            expanded = True
        else:
            status_icon = "🟢"
            status_text = "HOLD"
            expanded = False

        pnl_pct = h.get("unrealized_pnl_pct", 0)
        pnl_str = f"{pnl_pct:+.1f}%"

        with st.expander(
            f"{status_icon} **{ticker}** ({h['name'][:20]}) | {pnl_str} | {status_text}",
            expanded=expanded,
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("수량", f"{h['quantity']:.2f}주")
            c2.metric("평균매수가", f"${h['avg_buy_price']:.2f}")
            c3.metric("현재가", f"${h['current_price']:.2f}")
            c4.metric("수익률", pnl_str)

            if sig:
                _render_score_bars(sig)
                _render_exit_strategy(sig)
                st.markdown(f"**AI 신호:** {sig['signal']} (신뢰도: {int(sig['confidence']*100)}%)")
                st.markdown(f"**근거:** {sig['reasoning']}")

    # 재분석 버튼
    st.divider()
    if st.button("🔍 AI 매도 분석 실행", key="sell_analyze_bottom"):
        with st.spinner("매도 신호 병렬 분석 중... (약 30초)"):
            try:
                sell_analyzer.analyze_all_holdings()
                st.cache_data.clear()
                st.toast("재분석 완료!")
                st.rerun()
            except Exception as e:
                st.error(f"분석 실패: {e}")
