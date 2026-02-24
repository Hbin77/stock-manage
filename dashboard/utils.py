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


# ── 점수 해석 함수 ────────────────────────────────────────────────

def score_label(value: float | None, max_val: float = 10) -> tuple[str, str]:
    """(라벨, CSS클래스) 반환"""
    if value is None:
        return ("N/A", "interp-weak")
    ratio = value / max_val
    if ratio >= 0.8:
        return ("매우 강함", "interp-very-strong")
    elif ratio >= 0.6:
        return ("강함", "interp-strong")
    elif ratio >= 0.4:
        return ("보통", "interp-moderate")
    elif ratio >= 0.2:
        return ("약함", "interp-weak")
    else:
        return ("매우 약함", "interp-very-weak")


def confidence_label(conf_0to1: float | None) -> str:
    """신뢰도 해석 라벨"""
    if conf_0to1 is None:
        return "N/A"
    if conf_0to1 >= 0.90:
        return "매우 높음"
    elif conf_0to1 >= 0.75:
        return "높음"
    elif conf_0to1 >= 0.55:
        return "보통"
    else:
        return "낮음"


def fmt_upside(current: float | None, target: float | None) -> str:
    """상승률 포맷터"""
    if not current or not target or current <= 0:
        return "N/A"
    pct = (target - current) / current * 100
    if pct >= 0:
        return f"+{pct:.1f}% 상승 여력"
    else:
        return f"{pct:.1f}%"


def sell_pressure_label(sp: float | None) -> tuple[str, str]:
    """매도 압력 해석 (라벨, 색상)"""
    if sp is None:
        return ("N/A", "#8b949e")
    if sp >= 7.0:
        return ("STRONG SELL 영역", "#ef4444")
    elif sp >= 5.5:
        return ("SELL 영역", "#f59e0b")
    elif sp >= 3.5:
        return ("관찰", "#eab308")
    else:
        return ("안정", "#23c55e")


def rsi_signal(value: float | None) -> tuple[str, str]:
    """RSI 신호 (라벨, 색상)"""
    if value is None:
        return ("N/A", "#8b949e")
    if value < 30:
        return ("과매도", "#23c55e")
    elif value > 70:
        return ("과매수", "#ef4444")
    else:
        return ("중립", "#8b949e")


def html_score_bar(
    value: float | None,
    max_val: float = 10,
    color: str = "#58a6ff",
    label: str = "",
    thresholds: list[tuple[float, str]] | None = None,
) -> str:
    """임계값 수직선 포함 HTML 프로그레스 바"""
    if value is None:
        return f'<div class="score-bar-container"><span class="score-bar-label">{label}: N/A</span></div>'

    pct = min(max(value / max_val * 100, 0), 100)
    lbl, css_cls = score_label(value, max_val)

    threshold_html = ""
    if thresholds:
        for th_val, th_label in thresholds:
            th_pct = min(max(th_val / max_val * 100, 0), 100)
            threshold_html += (
                f'<div class="score-bar-threshold" style="left:{th_pct}%;">'
                f'<span class="score-bar-threshold-label">{th_label}</span></div>'
            )

    return (
        f'<div class="score-bar-container">'
        f'<div class="score-bar-label-row">'
        f'<span class="score-bar-label">{label}</span>'
        f'<span class="score-bar-value">{value:.1f}/{max_val:.0f}</span>'
        f'</div>'
        f'<div class="score-bar-track">'
        f'<div class="score-bar-fill" style="width:{pct}%;background:{color};"></div>'
        f'{threshold_html}'
        f'</div>'
        f'<span class="interp-label {css_cls}">{lbl}</span>'
        f'</div>'
    )


def exit_strategy_badge_html(strategy: str | None) -> str:
    """색상 코딩된 출구전략 뱃지 HTML"""
    badge_map = {
        "IMMEDIATE": ("즉시 매도", "exit-immediate"),
        "LIMIT_SELL": ("지정가 매도", "exit-limit"),
        "SCALE_OUT": ("분할 매도", "exit-scale-out"),
        "HOLD_WITH_STOP": ("손절가 보유", "exit-hold-stop"),
    }
    if not strategy or strategy not in badge_map:
        return f'<span class="exit-badge exit-hold-stop">{strategy or "N/A"}</span>'
    label, css = badge_map[strategy]
    return f'<span class="exit-badge {css}">{label}</span>'


def value_color(value: float | None, thresholds: list[tuple[float, str]]) -> str:
    """값에 따라 CSS 색상 반환. thresholds는 내림차순 [(경계, 색상), ...]"""
    if value is None:
        return "#8b949e"
    for boundary, color in thresholds:
        if value >= boundary:
            return color
    return thresholds[-1][1] if thresholds else "#8b949e"


def alert_type_badge_html(alert_type: str) -> str:
    """알림 유형 색상 뱃지 HTML"""
    badge_map = {
        "STOP_LOSS": ("손절", "alert-stop-loss"),
        "TARGET_PRICE": ("목표가", "alert-target"),
        "TRAILING_STOP": ("추적손절", "alert-trailing"),
        "VOLUME_SURGE": ("거래량", "alert-volume"),
    }
    label, css = badge_map.get(alert_type, (alert_type, "alert-stop-loss"))
    return f'<span class="alert-type-badge {css}">{label}</span>'
