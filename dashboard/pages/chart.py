"""
기술적 차트 페이지
캔들스틱 + 이동평균 + 볼린저밴드 + MACD + RSI + 거래량 복합 차트
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from config.settings import settings
from database.connection import get_db
from database.models import PriceHistory, Stock, TechnicalIndicator
from dashboard.utils import safe_div, rsi_signal, CACHE_TTL_MEDIUM


@st.cache_data(ttl=CACHE_TTL_MEDIUM)
def _load_chart_data(ticker: str, days: int = 90):
    """가격 + 지표 데이터를 캐시로 조회합니다."""
    try:
        with get_db() as db:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                return None, None

            price_rows = (
                db.query(PriceHistory)
                .filter(
                    PriceHistory.stock_id == stock.id,
                    PriceHistory.interval == "1d",
                )
                .order_by(PriceHistory.timestamp.desc())
                .limit(days)
                .all()
            )
            price_rows = list(reversed(price_rows))

            if not price_rows:
                return None, None

            price_df = pd.DataFrame([
                {
                    "date": r.timestamp,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in price_rows
            ])

            ind_rows = (
                db.query(TechnicalIndicator)
                .filter(TechnicalIndicator.stock_id == stock.id)
                .order_by(TechnicalIndicator.date.desc())
                .limit(days)
                .all()
            )
            ind_rows = list(reversed(ind_rows))

            ind_df = pd.DataFrame([
                {
                    "date": r.date,
                    "rsi_14": r.rsi_14,
                    "macd": r.macd,
                    "macd_signal": r.macd_signal,
                    "macd_hist": r.macd_hist,
                    "bb_upper": r.bb_upper,
                    "bb_middle": r.bb_middle,
                    "bb_lower": r.bb_lower,
                    "ma_20": r.ma_20,
                    "ma_50": r.ma_50,
                    "ma_200": r.ma_200,
                    "adx_14": r.adx_14,
                    "atr_14": r.atr_14,
                    "obv": r.obv,
                    "stoch_rsi_k": r.stoch_rsi_k,
                    "stoch_rsi_d": r.stoch_rsi_d,
                }
                for r in ind_rows
            ]) if ind_rows else pd.DataFrame()

        return price_df, ind_df
    except Exception:
        return None, None


def _build_chart(ticker: str, price_df: pd.DataFrame, ind_df: pd.DataFrame) -> go.Figure:
    """복합 차트 Figure를 생성합니다."""
    fig = make_subplots(
        rows=7,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.35, 0.10, 0.10, 0.12, 0.10, 0.10, 0.13],
        subplot_titles=[
            f"{ticker} 캔들스틱 + 이동평균 + 볼린저밴드",
            "MACD",
            "RSI",
            "거래량",
            "ADX",
            "StochRSI",
            "OBV",
        ],
    )

    dates = price_df["date"]

    # ── Row 1: 캔들스틱 ──────────────────────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=dates,
            open=price_df["open"],
            high=price_df["high"],
            low=price_df["low"],
            close=price_df["close"],
            name="OHLCV",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1, col=1,
    )

    ind_dates = ind_df["date"] if not ind_df.empty else pd.Series(dtype="object")

    if not ind_df.empty:
        # 이동평균선
        for col_name, color, label in [
            ("ma_20", "#ffa726", "MA20"),
            ("ma_50", "#42a5f5", "MA50"),
            ("ma_200", "#ab47bc", "MA200"),
        ]:
            if col_name in ind_df.columns:
                series = ind_df[col_name].dropna()
                if not series.empty:
                    fig.add_trace(
                        go.Scatter(
                            x=ind_dates[ind_df[col_name].notna()],
                            y=series,
                            mode="lines",
                            name=label,
                            line=dict(color=color, width=1.2),
                        ),
                        row=1, col=1,
                    )

        # 볼린저 밴드
        if "bb_upper" in ind_df.columns:
            bb_mask = ind_df["bb_upper"].notna()
            if bb_mask.any():
                fig.add_trace(
                    go.Scatter(
                        x=ind_dates[bb_mask],
                        y=ind_df.loc[bb_mask, "bb_upper"],
                        mode="lines",
                        name="BB Upper",
                        line=dict(color="rgba(200,200,200,0.5)", width=1, dash="dot"),
                    ),
                    row=1, col=1,
                )
                fig.add_trace(
                    go.Scatter(
                        x=ind_dates[bb_mask],
                        y=ind_df.loc[bb_mask, "bb_lower"],
                        mode="lines",
                        name="BB Lower",
                        fill="tonexty",
                        fillcolor="rgba(200,200,200,0.07)",
                        line=dict(color="rgba(200,200,200,0.5)", width=1, dash="dot"),
                    ),
                    row=1, col=1,
                )

        # ── Row 2: MACD ─────────────────────────────────────────────────
        if "macd" in ind_df.columns:
            macd_mask = ind_df["macd"].notna()
            if macd_mask.any():
                fig.add_trace(
                    go.Scatter(
                        x=ind_dates[macd_mask],
                        y=ind_df.loc[macd_mask, "macd"],
                        mode="lines",
                        name="MACD",
                        line=dict(color="#42a5f5", width=1.5),
                    ),
                    row=2, col=1,
                )
                fig.add_trace(
                    go.Scatter(
                        x=ind_dates[macd_mask],
                        y=ind_df.loc[macd_mask, "macd_signal"],
                        mode="lines",
                        name="Signal",
                        line=dict(color="#ffa726", width=1.5),
                    ),
                    row=2, col=1,
                )
                hist_vals = ind_df.loc[macd_mask, "macd_hist"]
                colors = ["#26a69a" if v >= 0 else "#ef5350" for v in hist_vals]
                fig.add_trace(
                    go.Bar(
                        x=ind_dates[macd_mask],
                        y=hist_vals,
                        name="MACD Hist",
                        marker_color=colors,
                        opacity=0.7,
                    ),
                    row=2, col=1,
                )

        # ── Row 3: RSI ──────────────────────────────────────────────────
        if "rsi_14" in ind_df.columns:
            rsi_mask = ind_df["rsi_14"].notna()
            if rsi_mask.any():
                fig.add_trace(
                    go.Scatter(
                        x=ind_dates[rsi_mask],
                        y=ind_df.loc[rsi_mask, "rsi_14"],
                        mode="lines",
                        name="RSI(14)",
                        line=dict(color="#ec407a", width=1.5),
                    ),
                    row=3, col=1,
                )
                fig.add_hline(y=70, line_dash="dash", line_color="rgba(255,100,100,0.6)",
                              annotation_text="과매수(70)", annotation_position="right", row=3, col=1)
                fig.add_hline(y=30, line_dash="dash", line_color="rgba(100,200,100,0.6)",
                              annotation_text="과매도(30)", annotation_position="right", row=3, col=1)

    # ── Row 4: 거래량 ──────────────────────────────────────────────────
    vol_colors = []
    for i in range(len(price_df)):
        if i == 0:
            vol_colors.append("#42a5f5")
        else:
            vol_colors.append("#26a69a" if price_df["close"].iloc[i] >= price_df["close"].iloc[i - 1] else "#ef5350")

    fig.add_trace(
        go.Bar(
            x=dates,
            y=price_df["volume"],
            name="거래량",
            marker_color=vol_colors,
            opacity=0.8,
        ),
        row=4, col=1,
    )

    # ── Row 5: ADX ──────────────────────────────────────────────────────
    if not ind_df.empty and "adx_14" in ind_df.columns:
        adx_mask = ind_df["adx_14"].notna()
        if adx_mask.any():
            fig.add_trace(
                go.Scatter(
                    x=ind_dates[adx_mask],
                    y=ind_df.loc[adx_mask, "adx_14"],
                    mode="lines",
                    name="ADX(14)",
                    line=dict(color="#ff9800", width=1.5),
                ),
                row=5, col=1,
            )
            fig.add_hline(y=25, line_dash="dash", line_color="rgba(255,152,0,0.5)",
                          annotation_text="추세 확인(25)", annotation_position="right", row=5, col=1)
            fig.add_hline(y=20, line_dash="dash", line_color="rgba(255,152,0,0.3)",
                          annotation_text="약한 추세(20)", annotation_position="right", row=5, col=1)

    # ── Row 6: StochRSI ────────────────────────────────────────────────
    if not ind_df.empty and "stoch_rsi_k" in ind_df.columns:
        srsi_k_mask = ind_df["stoch_rsi_k"].notna()
        if srsi_k_mask.any():
            fig.add_trace(
                go.Scatter(
                    x=ind_dates[srsi_k_mask],
                    y=ind_df.loc[srsi_k_mask, "stoch_rsi_k"],
                    mode="lines",
                    name="StochRSI K",
                    line=dict(color="#29b6f6", width=1.5),
                ),
                row=6, col=1,
            )
        srsi_d_mask = ind_df["stoch_rsi_d"].notna() if "stoch_rsi_d" in ind_df.columns else pd.Series(False, index=ind_df.index)
        if srsi_d_mask.any():
            fig.add_trace(
                go.Scatter(
                    x=ind_dates[srsi_d_mask],
                    y=ind_df.loc[srsi_d_mask, "stoch_rsi_d"],
                    mode="lines",
                    name="StochRSI D",
                    line=dict(color="#ffa726", width=1.5),
                ),
                row=6, col=1,
            )
        if srsi_k_mask.any() or srsi_d_mask.any():
            fig.add_hline(y=0.80, line_dash="dash", line_color="rgba(255,100,100,0.5)",
                          annotation_text="과매수(0.80)", annotation_position="right", row=6, col=1)
            fig.add_hline(y=0.20, line_dash="dash", line_color="rgba(100,200,100,0.5)",
                          annotation_text="과매도(0.20)", annotation_position="right", row=6, col=1)

    # ── Row 7: OBV ──────────────────────────────────────────────────────
    if not ind_df.empty and "obv" in ind_df.columns:
        obv_mask = ind_df["obv"].notna()
        if obv_mask.any():
            fig.add_trace(
                go.Scatter(
                    x=ind_dates[obv_mask],
                    y=ind_df.loc[obv_mask, "obv"],
                    mode="lines",
                    name="OBV",
                    line=dict(color="#66bb6a", width=1.5),
                    fill="tozeroy",
                    fillcolor="rgba(102,187,106,0.1)",
                ),
                row=7, col=1,
            )

    # ── 레이아웃 ────────────────────────────────────────────────────────
    fig.update_layout(
        template="plotly_dark",
        height=1200,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=20, t=60, b=20),
        xaxis_rangeslider_visible=False,
    )
    fig.update_yaxes(title_text="가격 (USD)", row=1, col=1)
    fig.update_yaxes(title_text="MACD", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
    fig.update_yaxes(title_text="거래량", row=4, col=1)
    fig.update_yaxes(title_text="ADX", row=5, col=1, range=[0, 60])
    fig.update_yaxes(title_text="StochRSI", row=6, col=1, range=[0, 1])
    fig.update_yaxes(title_text="OBV", row=7, col=1)

    return fig


def render():
    st.header("📊 기술적 분석 차트")

    # 종목 검색 + 기간 선택
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        search = st.text_input(
            "종목 검색 (티커 입력)",
            placeholder="예: AAPL, MSFT...",
            key="chart_search",
        ).strip().upper()
    with col2:
        all_tickers = settings.WATCHLIST_TICKERS
        if search:
            filtered = [t for t in all_tickers if search in t]
        else:
            filtered = all_tickers
        if search and not filtered:
            st.caption(f"'{search}' 검색 결과 없음 — 전체 목록에서 선택하세요")
        elif search:
            st.caption(f"'{search}' 검색 결과: {len(filtered)}개 종목")
        options = filtered[:30] if filtered else all_tickers[:30]
        ticker = st.selectbox(
            f"종목 선택 ({len(filtered)}개 매칭)" if search else f"종목 선택 ({len(all_tickers)}개)",
            options,
            key="chart_ticker",
        )
    with col3:
        period_map = {"1개월": 30, "3개월": 90, "6개월": 180, "1년": 365, "2년": 730, "5년": 1825}
        period_label = st.selectbox("기간", list(period_map.keys()), index=2, key="chart_period")
        days = period_map[period_label]

    price_df, ind_df = _load_chart_data(ticker, days)

    if price_df is None or price_df.empty:
        st.warning(f"[{ticker}] 가격 데이터가 없습니다. 먼저 `python main.py fetch` 를 실행하세요.")
        return

    # 최신 지표 요약 — safe_div 적용 + 신호 해석
    rsi_val = None
    macd_val = None
    macd_sig = None
    adx_val = None
    srsi_k_val = None

    if ind_df is not None and not ind_df.empty:
        latest = ind_df.iloc[-1]
        c1, c2, c3, c4, c5, c6 = st.columns(6)

        rsi_val = latest.get("rsi_14")
        rsi_lbl, _ = rsi_signal(rsi_val) if rsi_val is not None else ("N/A", "")
        c1.metric("RSI(14)", f"{rsi_val:.1f}" if rsi_val is not None else "N/A", delta=rsi_lbl if rsi_val is not None else None, delta_color="off")

        macd_val = latest.get("macd")
        macd_sig = latest.get("macd_signal")
        macd_delta = None
        if macd_val is not None and macd_sig is not None:
            macd_delta = "골든크로스 영역" if macd_val > macd_sig else "데드크로스 영역"
        c2.metric(
            "MACD",
            f"{macd_val:.3f}" if macd_val is not None else "N/A",
            delta=macd_delta,
            delta_color="off",
        )

        ma20 = latest.get("ma_20")
        current_close = price_df["close"].iloc[-1] if not price_df.empty else None
        pct_from_ma20 = safe_div(current_close - ma20, ma20) * 100 if ma20 and current_close else None
        c3.metric("vs MA20", f"{pct_from_ma20:+.2f}%" if pct_from_ma20 is not None else "N/A")

        ma50 = latest.get("ma_50")
        pct_from_ma50 = safe_div(current_close - ma50, ma50) * 100 if ma50 and current_close else None
        c4.metric("vs MA50", f"{pct_from_ma50:+.2f}%" if pct_from_ma50 is not None else "N/A")

        adx_val = latest.get("adx_14")
        adx_delta = None
        if adx_val is not None:
            if adx_val > 25:
                adx_delta = "강한 추세"
            elif adx_val > 20:
                adx_delta = "약한 추세"
            else:
                adx_delta = "추세 없음"
        c5.metric("ADX(14)", f"{adx_val:.1f}" if adx_val is not None else "N/A", delta=adx_delta, delta_color="off")

        srsi_k_val = latest.get("stoch_rsi_k")
        srsi_delta = None
        if srsi_k_val is not None:
            if srsi_k_val > 0.80:
                srsi_delta = "과매수"
            elif srsi_k_val < 0.20:
                srsi_delta = "과매도"
            else:
                srsi_delta = "중립"
        c6.metric("StochRSI K", f"{srsi_k_val:.2f}" if srsi_k_val is not None else "N/A", delta=srsi_delta, delta_color="off")

    # ── 기술 신호 요약 카드 ──────────────────────────────────────────
    signals = []
    # RSI
    if rsi_val is not None:
        rsi_lbl, rsi_col = rsi_signal(rsi_val)
        css = "signal-buy" if rsi_col == "#23c55e" else ("signal-sell" if rsi_col == "#ef4444" else "signal-neutral")
        signals.append(f'<span class="{css}">RSI {rsi_lbl}({rsi_val:.0f})</span>')
    # MACD
    if macd_val is not None and macd_sig is not None:
        if macd_val > macd_sig:
            signals.append('<span class="signal-buy">MACD 골든크로스</span>')
        else:
            signals.append('<span class="signal-sell">MACD 데드크로스</span>')
    # ADX
    if adx_val is not None:
        if adx_val > 25:
            signals.append(f'<span class="signal-buy">추세 강함(ADX {adx_val:.0f})</span>')
        elif adx_val < 20:
            signals.append(f'<span class="signal-neutral">추세 없음(ADX {adx_val:.0f})</span>')
    # StochRSI
    if srsi_k_val is not None:
        if srsi_k_val > 0.80:
            signals.append(f'<span class="signal-sell">StochRSI 과매수({srsi_k_val:.2f})</span>')
        elif srsi_k_val < 0.20:
            signals.append(f'<span class="signal-buy">StochRSI 과매도({srsi_k_val:.2f})</span>')

    # Count buy/sell signals
    buy_count = sum(1 for s in signals if "signal-buy" in s)
    sell_count = sum(1 for s in signals if "signal-sell" in s)
    overall = "매수 신호" if buy_count > sell_count else ("매도 신호" if sell_count > buy_count else "중립")

    if signals:
        st.markdown(
            f'<div class="signal-summary">[{overall}] {" | ".join(signals)}</div>',
            unsafe_allow_html=True,
        )

    # 차트 출력
    fig = _build_chart(ticker, price_df, ind_df if ind_df is not None else pd.DataFrame())
    st.plotly_chart(fig, use_container_width=True)
