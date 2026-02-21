"""
dashboard/style.py — 커스텀 CSS 인젝터

사용법:
    from dashboard.style import inject_custom_css
    inject_custom_css()   # main() 상단에서 한 번만 호출
"""
import streamlit as st


def inject_custom_css() -> None:
    """Streamlit 앱에 커스텀 CSS를 주입합니다."""
    st.markdown(
        """
        <style>
        /* ── 전역 폰트 & 배경 ───────────────────────────────────────────── */
        html, body, [class*="css"] {
            font-family: 'Pretendard', 'Noto Sans KR', 'Inter', sans-serif;
        }

        /* ── 사이드바 ─────────────────────────────────────────────────── */
        [data-testid="stSidebar"] {
            background-color: #0e1117 !important;
            border-right: 1px solid #21262d;
        }

        /* 사이드바 내 일반 텍스트를 약간 밝게 */
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] span {
            color: #c9d1d9;
        }

        /* 사이드바 종목 티커는 모노스페이스 */
        [data-testid="stSidebar"] code,
        [data-testid="stSidebar"] .ticker {
            font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
            font-size: 0.82rem;
            color: #58a6ff;
        }

        /* ── 다크 테마 메트릭 카드 ───────────────────────────────────── */
        [data-testid="metric-container"] {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 16px 20px;
            transition: box-shadow 0.25s ease, border-color 0.25s ease;
        }

        [data-testid="metric-container"]:hover {
            box-shadow: 0 4px 20px rgba(88, 166, 255, 0.15);
            border-color: #58a6ff;
        }

        [data-testid="metric-container"] [data-testid="stMetricLabel"] p {
            font-size: 0.78rem;
            color: #8b949e;
            letter-spacing: 0.03em;
            text-transform: uppercase;
        }

        [data-testid="metric-container"] [data-testid="stMetricValue"] {
            font-size: 1.6rem;
            font-weight: 700;
            color: #e6edf3;
        }

        [data-testid="metric-container"] [data-testid="stMetricDelta"] {
            font-size: 0.82rem;
        }

        /* ── 액션 뱃지 ────────────────────────────────────────────────── */
        .badge-buy, .badge-sell, .badge-hold {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            line-height: 1.6;
        }

        .badge-buy {
            background-color: rgba(35, 197, 94, 0.15);
            color: #23c55e;
            border: 1px solid rgba(35, 197, 94, 0.4);
        }

        .badge-sell {
            background-color: rgba(239, 68, 68, 0.15);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.4);
        }

        .badge-hold {
            background-color: rgba(156, 163, 175, 0.15);
            color: #9ca3af;
            border: 1px solid rgba(156, 163, 175, 0.4);
        }

        /* ── 손익 텍스트 클래스 ──────────────────────────────────────── */
        .profit {
            color: #23c55e !important;
            font-weight: 600;
        }

        .loss {
            color: #ef4444 !important;
            font-weight: 600;
        }

        /* ── 반응형 테이블 ───────────────────────────────────────────── */
        [data-testid="stDataFrame"] table,
        [data-testid="stTable"] table,
        .dataframe {
            font-size: 0.85rem !important;
            border-collapse: collapse;
        }

        [data-testid="stDataFrame"] th,
        [data-testid="stTable"] th,
        .dataframe th {
            background-color: #161b22 !important;
            color: #8b949e !important;
            font-size: 0.78rem !important;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            border-bottom: 1px solid #30363d !important;
            padding: 8px 12px !important;
        }

        [data-testid="stDataFrame"] td,
        [data-testid="stTable"] td,
        .dataframe td {
            font-size: 0.85rem !important;
            padding: 7px 12px !important;
            border-bottom: 1px solid #21262d !important;
            color: #c9d1d9;
        }

        [data-testid="stDataFrame"] tr:hover td,
        [data-testid="stTable"] tr:hover td {
            background-color: #1c2128 !important;
        }

        /* 작은 화면에서 테이블 폰트 추가 축소 */
        @media (max-width: 768px) {
            [data-testid="stDataFrame"] td,
            [data-testid="stTable"] td,
            .dataframe td {
                font-size: 0.75rem !important;
            }
        }

        /* ── 공통 섹션 헤더 ──────────────────────────────────────────── */
        h1, h2, h3 {
            color: #e6edf3;
        }

        h2 {
            border-bottom: 1px solid #21262d;
            padding-bottom: 6px;
            margin-bottom: 16px;
        }

        /* ── Streamlit 기본 버튼 오버라이드 ─────────────────────────── */
        [data-testid="baseButton-secondary"] {
            border: 1px solid #30363d !important;
            background-color: #161b22 !important;
            color: #c9d1d9 !important;
            border-radius: 6px !important;
            transition: border-color 0.2s ease, background-color 0.2s ease;
        }

        [data-testid="baseButton-secondary"]:hover {
            border-color: #58a6ff !important;
            background-color: #1c2128 !important;
            color: #e6edf3 !important;
        }

        /* ── Streamlit info / warning / success 박스 ────────────────── */
        [data-testid="stAlert"] {
            border-radius: 8px;
            border-left-width: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
