"""
dashboard/utils.py — 공통 유틸리티 (safe_call, 포맷터, 캐시 상수)
"""
import streamlit as st
from loguru import logger
from typing import Any, Callable

# ── 캐시 TTL 상수 ──────────────────────────────────────────────────
CACHE_TTL_REALTIME = 30    # 실시간 데이터 (추천, 보유현황)
CACHE_TTL_SHORT = 120      # 뉴스 등
CACHE_TTL_MEDIUM = 300     # 차트, 거래이력
CACHE_TTL_LONG = 1800      # 백테스팅 통계
CACHE_TTL_STATIC = 3600    # SPY YTD, 섹터 등

# ── Safe wrappers ──────────────────────────────────────────────────
def safe_call(fn: Callable, *args, default: Any = None, error_msg: str = "데이터 로딩 실패") -> Any:
    """백엔드 호출 래퍼 — 실패 시 toast + logger + default 반환"""
    try:
        return fn(*args)
    except Exception as e:
        logger.error(f"{error_msg}: {e}")
        st.toast(f"{error_msg}: {e}", icon="⚠️")
        return default

def safe_div(num: float | None, denom: float | None, default: float = 0.0) -> float:
    """0 나누기 방지"""
    if num is None or denom is None or denom == 0:
        return default
    return num / denom

# ── 포맷터 ────────────────────────────────────────────────────────
def fmt_dollar(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    if decimals == 0:
        return f"${value:,.0f}"
    return f"${value:,.{decimals}f}"

def fmt_pct(value: float | None, decimals: int = 1, with_sign: bool = True) -> str:
    if value is None:
        return "N/A"
    if with_sign:
        return f"{value:+.{decimals}f}%"
    return f"{value:.{decimals}f}%"

def fmt_score(value: float | None, max_val: float = 10.0, decimals: int = 1) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}/{max_val:.0f}"

def fmt_count(value: int | None, unit: str = "건") -> str:
    if value is None:
        return "N/A"
    return f"{value}{unit}"

# ── 캐시 무효화 ───────────────────────────────────────────────────
def clear_analysis_cache():
    """AI 분석 관련 캐시 전체 클리어"""
    st.cache_data.clear()

def clear_portfolio_cache():
    """포트폴리오 관련 캐시 전체 클리어"""
    st.cache_data.clear()

# ── UI 뱃지 헬퍼 ──────────────────────────────────────────────────
def action_badge_html(action: str) -> str:
    """BUY/SELL/HOLD 액션을 HTML 뱃지로 변환"""
    badge_map = {
        "STRONG_BUY": ('<span class="badge-buy">🟢🟢 STRONG BUY</span>', "badge-buy"),
        "BUY": ('<span class="badge-buy">🟢 BUY</span>', "badge-buy"),
        "HOLD": ('<span class="badge-hold">🟡 HOLD</span>', "badge-hold"),
        "SELL": ('<span class="badge-sell">🔴 SELL</span>', "badge-sell"),
        "STRONG_SELL": ('<span class="badge-sell">🔴🔴 STRONG SELL</span>', "badge-sell"),
    }
    html, _ = badge_map.get(action, (f'<span class="badge-hold">{action}</span>', "badge-hold"))
    return html

def urgency_icon(urgency: str) -> str:
    """긴급도 아이콘 반환"""
    return {"HIGH": "🔴", "NORMAL": "🟠", "LOW": "🟡"}.get(urgency, "⚪")

def signal_icon(signal: str) -> str:
    """매도 신호 아이콘 반환"""
    return {
        "STRONG_SELL": "📉📉",
        "SELL": "📉",
        "HOLD": "🟢",
    }.get(signal, "⚪")

def exit_strategy_label(strategy: str) -> tuple[str, str]:
    """출구전략 (label, icon) 반환"""
    strategies = {
        "IMMEDIATE": ("즉시 매도", "🔴"),
        "LIMIT_SELL": ("지정가 매도", "🟠"),
        "SCALE_OUT": ("분할 매도", "🟡"),
        "HOLD_WITH_STOP": ("손절가 설정 후 보유", "🟢"),
    }
    return strategies.get(strategy, (strategy or "N/A", "⚪"))
