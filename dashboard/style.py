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
        /* ── Streamlit 자동 멀티페이지 네비게이션 숨김 ─────────────────── */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* ── 전역 폰트 & 배경 ───────────────────────────────────────────── */
        html, body, [class*="css"] {
            font-family: 'Pretendard', 'Noto Sans KR', 'Inter', sans-serif;
        }

        /* ── 사이드바 ─────────────────────────────────────────────────── */
        [data-testid="stSidebar"] {
            background-color: #0e1117 !important;
            border-right: 1px solid #21262d;
        }

        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] span {
            color: #c9d1d9;
        }

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

        /* ── 카드 컨테이너 ───────────────────────────────────────────── */
        .card {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 16px 20px;
            margin-bottom: 12px;
            transition: box-shadow 0.25s ease, border-color 0.25s ease;
        }

        .card:hover {
            box-shadow: 0 4px 20px rgba(88, 166, 255, 0.12);
            border-color: #58a6ff;
        }

        /* ── 프로그레스 라벨 ──────────────────────────────────────────── */
        .progress-label {
            font-size: 0.75rem;
            color: #8b949e;
            margin-bottom: 2px;
            letter-spacing: 0.02em;
        }

        /* ── 액션 뱃지 ────────────────────────────────────────────────── */
        .badge-buy, .badge-sell, .badge-hold, .badge-strong-buy {
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

        .badge-strong-buy {
            background-color: rgba(35, 197, 94, 0.25);
            color: #22c55e;
            border: 1px solid rgba(35, 197, 94, 0.6);
            font-weight: 700;
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

        /* ── 긴급도 클래스 ────────────────────────────────────────────── */
        .urgency-high {
            color: #ef4444 !important;
            font-weight: 700;
        }

        .urgency-normal {
            color: #f59e0b !important;
            font-weight: 600;
        }

        .urgency-low {
            color: #eab308 !important;
            font-weight: 500;
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

        /* ── Score Bar ──────────────────────────────────────────────── */
        .score-bar-container {
            margin-bottom: 8px;
        }

        .score-bar-label-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 3px;
        }

        .score-bar-label {
            font-size: 0.75rem;
            color: #8b949e;
            font-weight: 500;
        }

        .score-bar-value {
            font-size: 0.78rem;
            color: #e6edf3;
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }

        .score-bar-track {
            position: relative;
            width: 100%;
            height: 8px;
            background: #21262d;
            border-radius: 4px;
            overflow: visible;
        }

        .score-bar-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.4s ease;
        }

        .score-bar-threshold {
            position: absolute;
            top: -2px;
            width: 2px;
            height: 12px;
            background: #e6edf3;
            border-radius: 1px;
        }

        .score-bar-threshold-label {
            position: absolute;
            top: -16px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 0.6rem;
            color: #8b949e;
            white-space: nowrap;
        }

        /* ── 해석 라벨 ──────────────────────────────────────────────── */
        .interp-label {
            display: inline-block;
            font-size: 0.7rem;
            font-weight: 500;
            margin-top: 2px;
            padding: 1px 6px;
            border-radius: 4px;
        }

        .interp-very-strong {
            color: #23c55e;
            background: rgba(35, 197, 94, 0.12);
        }

        .interp-strong {
            color: #58a6ff;
            background: rgba(88, 166, 255, 0.12);
        }

        .interp-moderate {
            color: #eab308;
            background: rgba(234, 179, 8, 0.12);
        }

        .interp-weak {
            color: #f59e0b;
            background: rgba(245, 158, 11, 0.12);
        }

        .interp-very-weak {
            color: #ef4444;
            background: rgba(239, 68, 68, 0.12);
        }

        /* ── 상승률 뱃지 ────────────────────────────────────────────── */
        .upside-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .upside-positive {
            color: #23c55e;
            background: rgba(35, 197, 94, 0.15);
            border: 1px solid rgba(35, 197, 94, 0.4);
        }

        .upside-negative {
            color: #ef4444;
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.4);
        }

        /* ── 긴급도 헤더 ────────────────────────────────────────────── */
        .urgency-header {
            padding: 10px 16px;
            border-radius: 8px;
            margin-bottom: 12px;
            font-weight: 600;
            font-size: 0.95rem;
            border-left: 4px solid;
        }

        .urgency-header-high {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.20), rgba(239, 68, 68, 0.08));
            border-left-color: #ef4444;
            color: #fca5a5;
        }

        .urgency-header-normal {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.18), rgba(245, 158, 11, 0.06));
            border-left-color: #f59e0b;
            color: #fcd34d;
        }

        .urgency-header-low {
            background: linear-gradient(135deg, rgba(107, 114, 128, 0.15), rgba(107, 114, 128, 0.05));
            border-left-color: #6b7280;
            color: #d1d5db;
        }

        /* ── 출구전략 뱃지 ──────────────────────────────────────────── */
        .exit-badge {
            display: inline-block;
            padding: 6px 16px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 700;
            letter-spacing: 0.03em;
        }

        .exit-immediate {
            background: rgba(239, 68, 68, 0.20);
            color: #fca5a5;
            border: 1px solid rgba(239, 68, 68, 0.5);
        }

        .exit-limit {
            background: rgba(245, 158, 11, 0.20);
            color: #fcd34d;
            border: 1px solid rgba(245, 158, 11, 0.5);
        }

        .exit-scale-out {
            background: rgba(234, 179, 8, 0.18);
            color: #fde047;
            border: 1px solid rgba(234, 179, 8, 0.5);
        }

        .exit-hold-stop {
            background: rgba(35, 197, 94, 0.15);
            color: #86efac;
            border: 1px solid rgba(35, 197, 94, 0.5);
        }

        /* ── Top Pick 카드 ──────────────────────────────────────────── */
        .top-pick-card {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 16px 20px;
            margin-bottom: 12px;
            border-left: 4px solid #6b7280;
            transition: box-shadow 0.25s ease;
        }

        .top-pick-card:hover {
            box-shadow: 0 4px 20px rgba(88, 166, 255, 0.12);
        }

        .top-pick-card.strong-buy {
            border-left-color: #23c55e;
        }

        .top-pick-card.buy {
            border-left-color: #58a6ff;
        }

        .top-pick-card.hold {
            border-left-color: #eab308;
        }

        /* ── 감성 뱃지(대형) ────────────────────────────────────────── */
        .sentiment-badge-lg {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .sentiment-positive-lg {
            color: #23c55e;
            background: rgba(35, 197, 94, 0.15);
            border: 1px solid rgba(35, 197, 94, 0.4);
        }

        .sentiment-negative-lg {
            color: #ef4444;
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.4);
        }

        .sentiment-neutral-lg {
            color: #eab308;
            background: rgba(234, 179, 8, 0.12);
            border: 1px solid rgba(234, 179, 8, 0.4);
        }

        /* ── 알림 유형 뱃지 ──────────────────────────────────────────── */
        .alert-type-badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.03em;
        }

        .alert-stop-loss {
            background: rgba(239, 68, 68, 0.18);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.4);
        }

        .alert-target {
            background: rgba(35, 197, 94, 0.15);
            color: #23c55e;
            border: 1px solid rgba(35, 197, 94, 0.4);
        }

        .alert-trailing {
            background: rgba(88, 166, 255, 0.15);
            color: #58a6ff;
            border: 1px solid rgba(88, 166, 255, 0.4);
        }

        .alert-volume {
            background: rgba(245, 158, 11, 0.18);
            color: #f59e0b;
            border: 1px solid rgba(245, 158, 11, 0.4);
        }

        /* ── 가중치 시각화 ──────────────────────────────────────────── */
        .pillar-container {
            display: flex;
            width: 100%;
            height: 24px;
            border-radius: 6px;
            overflow: hidden;
            margin: 4px 0;
        }

        .pillar-segment {
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.68rem;
            font-weight: 600;
            color: #e6edf3;
            white-space: nowrap;
            overflow: hidden;
        }

        .pillar-label {
            display: flex;
            justify-content: space-between;
            font-size: 0.7rem;
            color: #8b949e;
            margin-top: 2px;
        }

        /* ── 실현손익 미리보기 ──────────────────────────────────────── */
        .pnl-preview-profit {
            background: rgba(35, 197, 94, 0.12);
            border: 1px solid rgba(35, 197, 94, 0.3);
            border-radius: 8px;
            padding: 10px 16px;
            color: #23c55e;
            font-weight: 600;
        }

        .pnl-preview-loss {
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 8px;
            padding: 10px 16px;
            color: #ef4444;
            font-weight: 600;
        }

        /* ── 기술 신호 요약 카드 ────────────────────────────────────── */
        .signal-summary {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 10px 16px;
            margin-bottom: 12px;
            font-size: 0.85rem;
        }

        .signal-summary .signal-buy {
            color: #23c55e;
            font-weight: 600;
        }

        .signal-summary .signal-sell {
            color: #ef4444;
            font-weight: 600;
        }

        .signal-summary .signal-neutral {
            color: #8b949e;
        }

        /* ── 감성 분포 바 ──────────────────────────────────────────── */
        .sentiment-dist-bar {
            display: flex;
            width: 100%;
            height: 20px;
            border-radius: 6px;
            overflow: hidden;
            margin: 6px 0;
        }

        .sentiment-dist-bar .seg-positive {
            background: #23c55e;
        }

        .sentiment-dist-bar .seg-neutral {
            background: #eab308;
        }

        .sentiment-dist-bar .seg-negative {
            background: #ef4444;
        }

        /* ── 모바일 반응형 ───────────────────────────────────────────── */
        @media (max-width: 768px) {
            [data-testid="stDataFrame"] td,
            [data-testid="stTable"] td,
            .dataframe td {
                font-size: 0.75rem !important;
                padding: 5px 8px !important;
            }

            [data-testid="stDataFrame"] th,
            [data-testid="stTable"] th,
            .dataframe th {
                font-size: 0.70rem !important;
                padding: 5px 8px !important;
            }

            [data-testid="metric-container"] {
                padding: 10px 12px;
            }

            [data-testid="metric-container"] [data-testid="stMetricValue"] {
                font-size: 1.2rem;
            }

            [data-testid="metric-container"] [data-testid="stMetricLabel"] p {
                font-size: 0.70rem;
            }

            .card {
                padding: 10px 12px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
