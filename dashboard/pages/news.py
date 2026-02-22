"""
뉴스 피드 페이지
수집된 시장 뉴스를 감성 점수와 함께 표시합니다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from datetime import datetime, timedelta

import streamlit as st
import pandas as pd

from config.settings import settings
from database.connection import get_db
from database.models import MarketNews

try:
    from config.tickers import get_tickers_by_index
    _HAS_TICKERS = True
except ImportError:
    _HAS_TICKERS = False


@st.cache_data(ttl=120)
def _load_news(ticker_filter: str | None, days: int) -> list[dict]:
    """뉴스 데이터를 120초 캐시로 조회합니다."""
    cutoff = datetime.now() - timedelta(days=days)

    with get_db() as db:
        query = db.query(MarketNews).filter(MarketNews.published_at >= cutoff)
        if ticker_filter and ticker_filter != "전체":
            query = query.filter(MarketNews.ticker == ticker_filter)
        rows = query.order_by(MarketNews.published_at.desc()).limit(100).all()

        return [
            {
                "ticker": r.ticker or "시장 전반",
                "title": r.title,
                "summary": r.summary or "",
                "url": r.url,
                "source": r.source or "N/A",
                "sentiment": r.sentiment,
                "published_at": r.published_at.strftime("%Y-%m-%d %H:%M") if r.published_at else "N/A",
            }
            for r in rows
        ]


def _sentiment_badge(sentiment: float | None) -> str:
    """감성 점수를 배지 텍스트로 변환합니다."""
    if sentiment is None:
        return "⚪ N/A"
    if sentiment > 0.2:
        return f"🟢 {sentiment:+.2f}"
    elif sentiment < -0.2:
        return f"🔴 {sentiment:+.2f}"
    else:
        return f"🟡 {sentiment:+.2f}"


def render():
    st.header("📰 뉴스 피드")

    # ── 필터 ─────────────────────────────────────────────────────────────────
    filter_col, days_col = st.columns([3, 1])

    with days_col:
        days = st.selectbox("기간", [1, 3, 7, 14, 30], index=2, key="news_days",
                            format_func=lambda d: f"최근 {d}일")

    with filter_col:
        # 텍스트 검색 + 인덱스 탭 필터
        search_input = st.text_input(
            "종목 검색",
            placeholder="티커 입력 (예: AAPL)...",
            key="news_search",
        ).strip().upper()

    # 인덱스 탭
    if _HAS_TICKERS:
        tab_all, tab_nasdaq, tab_sp500 = st.tabs(["전체", "NASDAQ100", "S&P500"])
    else:
        tab_all = st.container()
        tab_nasdaq = tab_sp500 = None

    def _render_news_tab(ticker_filter: str | None):
        news_list = _load_news(ticker_filter, days)

        if not news_list:
            st.info("뉴스 데이터가 없습니다. `python main.py fetch`를 실행하여 뉴스를 수집하세요.")
            return

        # 텍스트 검색 적용
        if search_input:
            news_list = [n for n in news_list if search_input in n["ticker"].upper()]

        # ── 감성 요약 ────────────────────────────────────────────────────────
        sentiments = [n["sentiment"] for n in news_list if n["sentiment"] is not None]
        if sentiments:
            avg_sent = sum(sentiments) / len(sentiments)
            pos_count = sum(1 for s in sentiments if s > 0.2)
            neg_count = sum(1 for s in sentiments if s < -0.2)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("전체 뉴스", f"{len(news_list)}건")
            c2.metric("평균 감성", f"{avg_sent:+.3f}")
            c3.metric("긍정 뉴스", f"{pos_count}건")
            c4.metric("부정 뉴스", f"{neg_count}건")
            st.divider()

        # ── 뉴스 목록 ─────────────────────────────────────────────────────────
        for n in news_list:
            sentiment_text = _sentiment_badge(n["sentiment"])

            with st.container():
                col_badge, col_content = st.columns([1, 7])

                with col_badge:
                    st.markdown(f"**{n['ticker']}**")
                    st.markdown(sentiment_text)
                    st.caption(n["published_at"])

                with col_content:
                    if n.get("url"):
                        st.markdown(f"**[{n['title']}]({n['url']})**")
                    else:
                        st.markdown(f"**{n['title']}**")

                    if n["summary"]:
                        st.markdown(f"<small>{n['summary'][:200]}{'...' if len(n['summary']) > 200 else ''}</small>",
                                    unsafe_allow_html=True)
                    st.caption(f"출처: {n['source']}")

                st.divider()

    with tab_all:
        _render_news_tab(None)

    if _HAS_TICKERS and tab_nasdaq and tab_sp500:
        # NASDAQ100 탭: 해당 인덱스 종목만 필터링
        with tab_nasdaq:
            nasdaq_tickers = get_tickers_by_index("NASDAQ100")
            # DB에서 종목별 필터가 없으므로 전체 로드 후 탭에서 필터
            news_all = _load_news(None, days)
            if news_all:
                filtered = [n for n in news_all if n["ticker"] in nasdaq_tickers]
                if search_input:
                    filtered = [n for n in filtered if search_input in n["ticker"].upper()]
                if not filtered:
                    st.info("NASDAQ100 종목 뉴스가 없습니다.")
                else:
                    for n in filtered:
                        with st.container():
                            col_badge, col_content = st.columns([1, 7])
                            with col_badge:
                                st.markdown(f"**{n['ticker']}**")
                                st.markdown(_sentiment_badge(n["sentiment"]))
                                st.caption(n["published_at"])
                            with col_content:
                                if n.get("url"):
                                    st.markdown(f"**[{n['title']}]({n['url']})**")
                                else:
                                    st.markdown(f"**{n['title']}**")
                                if n["summary"]:
                                    st.markdown(f"<small>{n['summary'][:200]}</small>", unsafe_allow_html=True)
                                st.caption(f"출처: {n['source']}")
                            st.divider()
            else:
                st.info("뉴스 데이터가 없습니다.")

        with tab_sp500:
            sp500_tickers = get_tickers_by_index("SP500")
            news_all = _load_news(None, days)
            if news_all:
                filtered = [n for n in news_all if n["ticker"] in sp500_tickers]
                if search_input:
                    filtered = [n for n in filtered if search_input in n["ticker"].upper()]
                if not filtered:
                    st.info("S&P500 종목 뉴스가 없습니다.")
                else:
                    for n in filtered:
                        with st.container():
                            col_badge, col_content = st.columns([1, 7])
                            with col_badge:
                                st.markdown(f"**{n['ticker']}**")
                                st.markdown(_sentiment_badge(n["sentiment"]))
                                st.caption(n["published_at"])
                            with col_content:
                                if n.get("url"):
                                    st.markdown(f"**[{n['title']}]({n['url']})**")
                                else:
                                    st.markdown(f"**{n['title']}**")
                                if n["summary"]:
                                    st.markdown(f"<small>{n['summary'][:200]}</small>", unsafe_allow_html=True)
                                st.caption(f"출처: {n['source']}")
                            st.divider()
            else:
                st.info("뉴스 데이터가 없습니다.")
