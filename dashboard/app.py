"""
주식 관리 자동화 시스템 — Streamlit 웹 대시보드

실행:
  streamlit run dashboard/app.py --server.port 8501
"""
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from loguru import logger

# 페이지 설정 (반드시 첫 번째 streamlit 호출이어야 함)
st.set_page_config(
    page_title="주식 관리 시스템",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 로그 설정 (파일 출력 억제)
from config.settings import settings
logger.remove()
logger.add(
    settings.LOG_FILE,
    level="DEBUG",
    rotation="10 MB",
    retention="30 days",
    compression="zip",
    encoding="utf-8",
)

# 페이지 임포트
from dashboard.pages import portfolio, chart, ai_buy, ai_sell, news
from dashboard.style import inject_custom_css


# ── 사이드바 네비게이션 ────────────────────────────────────────────────────────
def sidebar_nav() -> str:
    st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2103/2103632.png", width=60)
    st.sidebar.title("📈 주식 관리 시스템")
    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "메뉴",
        options=[
            "💼 포트폴리오",
            "📊 차트 분석",
            "🤖 AI 매수 추천",
            "📉 AI 매도 신호",
            "📰 뉴스 피드",
        ],
        key="nav",
    )

    st.sidebar.markdown("---")
    # 종목 수 요약만 표시 (600개 리스트 나열 제거)
    try:
        from config.tickers import NASDAQ_100, SP500, ALL_TICKERS
        nasdaq_count = len(set(NASDAQ_100))
        sp500_count = len(set(SP500))
        total_count = len(ALL_TICKERS)
        watchlist_count = len(settings.WATCHLIST_TICKERS)
        st.sidebar.markdown("### 모니터링 종목")
        st.sidebar.info(
            f"**NASDAQ100**: {nasdaq_count}개  \n"
            f"**S&P 500**: {sp500_count}개  \n"
            f"**전체 (중복 제거)**: {total_count}개  \n"
            f"**현재 설정**: {watchlist_count}개"
        )
    except ImportError:
        watchlist_count = len(settings.WATCHLIST_TICKERS)
        st.sidebar.markdown("### 관심 종목")
        st.sidebar.info(f"현재 설정: {watchlist_count}개")

    st.sidebar.markdown("---")
    st.sidebar.caption("스케줄러 실행 중인 경우 데이터가 자동으로 갱신됩니다.")
    st.sidebar.caption("`python main.py run` 으로 스케줄러 시작")

    return page


# ── 메인 앱 ──────────────────────────────────────────────────────────────────
def main():
    inject_custom_css()
    page = sidebar_nav()

    if page == "💼 포트폴리오":
        portfolio.render()
    elif page == "📊 차트 분석":
        chart.render()
    elif page == "🤖 AI 매수 추천":
        ai_buy.render()
    elif page == "📉 AI 매도 신호":
        ai_sell.render()
    elif page == "📰 뉴스 피드":
        news.render()


if __name__ == "__main__":
    main()
