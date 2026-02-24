"""
AI 매도 신호 페이지
보유 종목별 SELL/HOLD 상태를 표시합니다.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from analysis.sell_analyzer import sell_analyzer
from portfolio.portfolio_manager import portfolio_manager
from dashboard.utils import (
    safe_call, safe_div, fmt_dollar, fmt_pct, fmt_score, fmt_count,
    clear_analysis_cache, urgency_icon, signal_icon, exit_strategy_label,
    CACHE_TTL_REALTIME,
)


# ── 캐시 함수 ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL_REALTIME)
def _get_sell_signals():
    return safe_call(sell_analyzer.get_active_sell_signals, default=[])


@st.cache_data(ttl=CACHE_TTL_REALTIME)
def _get_holdings():
    return safe_call(portfolio_manager.get_holdings, False, default=[])


# ── 헬퍼 함수 ──────────────────────────────────────────────────────────────

def _render_score_bars(s: dict):
    """스코어(technical, position_risk, fundamental, sell_pressure) progress bar 표시"""
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
    """exit_strategy 뱃지 표시"""
    exit_strat = s.get("exit_strategy")
    if not exit_strat:
        return
    label, icon = exit_strategy_label(exit_strat)
    st.markdown(f"**매도 전략:** {icon} {label}")


def _render_summary(signals: list[dict], total_holdings: int):
    """매도 종합 요약"""
    sell_count = sum(1 for s in signals if s.get("signal") in ("SELL", "STRONG_SELL"))
    confidences = [s["confidence"] for s in signals if s.get("confidence") is not None]
    avg_conf = safe_div(sum(confidences), len(confidences))

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("전체 보유 종목", fmt_count(total_holdings, unit="개"))
    mc2.metric(
        "SELL 신호",
        fmt_count(sell_count, unit="개"),
        delta=f"{sell_count}개 매도 권고" if sell_count > 0 else None,
        delta_color="inverse" if sell_count > 0 else "off",
    )
    mc3.metric("평균 신뢰도", fmt_pct(avg_conf * 100, decimals=0, with_sign=False))


# ── 메인 렌더 ──────────────────────────────────────────────────────────────

def render():
    st.header("📉 AI 매도 신호")

    holdings = _get_holdings()
    if not holdings:
        st.info("보유 종목이 없습니다.")
        return

    signals = _get_sell_signals()
    signal_map = {s["ticker"]: s for s in signals}

    # ── 분석 실행 버튼 (단일 — 기존 중복 제거) ──────────────────────────
    btn_col, info_col = st.columns([1, 3])
    with btn_col:
        run_sell = st.button("🔍 AI 매도 분석 실행", type="primary")
    with info_col:
        if signals:
            st.caption(f"마지막 분석: {signals[0].get('signal_date', 'N/A')} | {len(signals)}개 신호")
        else:
            st.caption("오늘의 매도 분석이 아직 실행되지 않았습니다.")

    if run_sell:
        progress = st.progress(0, text="매도 분석 준비 중...")
        try:
            progress.progress(10, text="보유 종목 매도 신호 분석 중... (약 30초)")
            results = sell_analyzer.analyze_all_holdings()
            sell_count = sum(1 for s in results.values() if s in ("SELL", "STRONG_SELL"))
            progress.progress(100, text="완료!")
            st.toast(f"매도 분석 완료! SELL {sell_count}건 / 전체 {len(results)}건")
            clear_analysis_cache()
            time.sleep(0.5)
            st.rerun()
        except Exception as e:
            progress.empty()
            st.error(f"매도 분석 실패: {e}")

    st.divider()

    # ── 매도 종합 요약 ──────────────────────────────────────────────────
    if signals:
        _render_summary(signals, len(holdings))
        st.divider()

    # ── 매도 신호 종목 (SELL/STRONG_SELL) ──────────────────────────────
    sell_signals = [s for s in signals if s.get("signal") in ("SELL", "STRONG_SELL")]

    if sell_signals:
        st.markdown(f"⚠️ **매도 신호 감지: {len(sell_signals)}개 종목**")
        for s in sell_signals:
            u_icon = urgency_icon(s.get("urgency", ""))
            s_icon = signal_icon(s.get("signal", ""))
            pnl_pct = s.get("current_pnl_pct") or 0
            conf = int((s.get("confidence") or 0) * 100)

            with st.expander(
                f"{u_icon}{s_icon} **{s['ticker']}** — {s['signal']} "
                f"(수익률: {pnl_pct:+.1f}%, 신뢰도: {conf}%)",
                expanded=True,
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("현재가", fmt_dollar(s.get("current_price")))
                c2.metric("제안 매도가", fmt_dollar(s.get("suggested_sell_price")))
                c3.metric(
                    "현재 수익률",
                    fmt_pct(pnl_pct),
                    delta_color="normal" if pnl_pct >= 0 else "inverse",
                )

                _render_score_bars(s)
                _render_exit_strategy(s)

                col_u, col_s = st.columns(2)
                col_u.markdown(f"**긴급도:** {s.get('urgency', 'N/A')}")
                col_s.markdown(f"**신뢰도:** {conf}%")

                st.markdown(f"**AI 분석:** {s.get('reasoning', '')}")
                st.caption(f"분석 시각: {s.get('signal_date', 'N/A')}")
    elif signals:
        st.success("✅ 현재 매도 신호가 없습니다. 모든 보유 종목이 안정적입니다.")
    else:
        st.info("매도 분석을 먼저 실행하세요.")

    st.divider()

    # ── 전체 보유 종목 상태 ─────────────────────────────────────────────
    st.subheader("보유 종목 전체 현황")

    for h in holdings:
        ticker = h["ticker"]
        sig = signal_map.get(ticker)

        if sig is None:
            status_icon = "⚪"
            status_text = "미분석"
            expanded = False
        elif sig.get("signal") in ("SELL", "STRONG_SELL"):
            status_icon = "🔴"
            status_text = sig["signal"]
            expanded = True
        else:
            status_icon = "🟢"
            status_text = "HOLD"
            expanded = False

        pnl_pct = h.get("unrealized_pnl_pct") or 0
        pnl_str = fmt_pct(pnl_pct)

        with st.expander(
            f"{status_icon} **{ticker}** ({(h.get('name') or '')[:20]}) | {pnl_str} | {status_text}",
            expanded=expanded,
        ):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("수량", f"{h.get('quantity', 0):.2f}주")
            c2.metric("평균매수가", fmt_dollar(h.get("avg_buy_price")))
            c3.metric("현재가", fmt_dollar(h.get("current_price")))
            c4.metric("수익률", pnl_str)

            if sig:
                _render_score_bars(sig)
                _render_exit_strategy(sig)
                conf = int((sig.get("confidence") or 0) * 100)
                st.markdown(f"**AI 신호:** {sig.get('signal', 'N/A')} (신뢰도: {conf}%)")
                st.markdown(f"**근거:** {sig.get('reasoning', '')}")
