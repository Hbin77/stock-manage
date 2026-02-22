"""
가격 알림 매니저
손절가/목표가/거래량 급등 조건을 감시하고 카카오 알림을 발송합니다.

발화 조건:
  - STOP_LOSS   : current_price <= threshold_value
  - TARGET_PRICE: current_price >= threshold_value
  - VOLUME_SURGE: 오늘 거래량 >= volume_ma_20 × threshold_value(배수)

중복 방지:
  - COOLDOWN_MINUTES(60분) 이내 동일 종목×유형 재발화 억제
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import and_, desc

from database.connection import get_db
from database.models import (
    AIRecommendation,
    AlertHistory,
    PortfolioHolding,
    PriceAlert,
    PriceHistory,
    Stock,
    TechnicalIndicator,
)

__all__ = ["AlertManager", "VALID_ALERT_TYPES", "alert_manager"]

# ── 모듈 상수 ──────────────────────────────────────────────────────────────────
VALID_ALERT_TYPES: frozenset = frozenset({"STOP_LOSS", "TARGET_PRICE", "VOLUME_SURGE", "TRAILING_STOP"})


# ── 내부 헬퍼 데이터클래스 ────────────────────────────────────────────────────
@dataclass(frozen=True)
class _AlertCondition:
    """DB 레코드 없이 fallback 임계값을 표현하는 경량 데이터 홀더.

    check_portfolio_alerts에서 AIRecommendation의 stop_loss/target_price를
    PriceAlert ORM 객체 없이 표현할 때 사용합니다.
    """
    alert_type: str
    threshold_value: float


class AlertManager:
    """가격 알림 체크 및 발송 매니저"""

    COOLDOWN_MINUTES = 60  # 기본 쿨다운 (COOLDOWN_MAP에 없는 유형용)
    COOLDOWN_MAP = {
        "STOP_LOSS": 15,       # 손절 알림은 15분마다
        "TRAILING_STOP": 15,   # 트레일링 스톱도 15분
        "TARGET_PRICE": 60,    # 목표가는 60분
        "VOLUME_SURGE": 360,   # 거래량 급등은 하루에 ~1회
    }
    TRAILING_STOP_PCT = 0.10  # 최고가 대비 -10% 하락 시 트레일링 스톱 발동 (ATR 없을 때 기본값)

    # ── 내부 유틸리티 ──────────────────────────────────────────────────────────

    def _now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def _is_in_cooldown(self, db, stock_id: int, alert_type: str) -> bool:
        """마지막 발화 후 유형별 쿨다운 시간 이내이면 True"""
        cooldown_minutes = self.COOLDOWN_MAP.get(alert_type, self.COOLDOWN_MINUTES)
        cutoff = self._now() - timedelta(minutes=cooldown_minutes)
        recent = (
            db.query(AlertHistory)
            .filter(
                and_(
                    AlertHistory.stock_id == stock_id,
                    AlertHistory.alert_type == alert_type,
                    AlertHistory.triggered_at >= cutoff,
                )
            )
            .first()
        )
        return recent is not None

    def _record_alert(self, db, stock_id: int, alert_type: str,
                      trigger_price: Optional[float], message: str) -> AlertHistory:
        """AlertHistory 저장"""
        ah = AlertHistory(
            stock_id=stock_id,
            alert_type=alert_type,
            trigger_price=trigger_price,
            triggered_at=self._now(),
            message=message,
            is_sent=False,
        )
        db.add(ah)
        return ah

    def _fire_alert(
        self,
        db,
        stock: Stock,
        alert_type: str,
        current_price: float,
        threshold: float,
        extra: Optional[dict] = None,
        orm_alert: Optional[PriceAlert] = None,
    ) -> Optional[dict]:
        """쿨다운 체크 → AlertHistory 저장 → 결과 dict 반환.

        check_portfolio_alerts와 check_volume_surge 양쪽에서 공유하는
        알림 발화의 단일 진입점입니다.

        Args:
            db           : 활성 SQLAlchemy 세션.
            stock        : 발화 대상 Stock ORM 객체.
            alert_type   : VALID_ALERT_TYPES 중 하나.
            current_price: 평가 시점의 현재가 또는 종가.
            threshold    : 초과된 임계값.
            extra        : 결과 dict에 병합할 추가 키 (거래량 관련 필드 등).
            orm_alert    : 실제 PriceAlert 레코드가 있을 경우 전달하여
                           last_triggered_at 갱신에 사용.

        Returns:
            발화 성공 시 결과 dict, 쿨다운으로 억제된 경우 None.
        """
        if self._is_in_cooldown(db, stock.id, alert_type):
            return None

        msg = (
            f"[{alert_type}] {stock.ticker} ({stock.name}) "
            f"현재가 ${current_price:.2f} / 기준 ${threshold:.2f}"
        )
        ah = self._record_alert(db, stock.id, alert_type, current_price, msg)
        ah.is_sent = True

        if orm_alert is not None and getattr(orm_alert, "id", None):
            orm_alert.last_triggered_at = self._now()

        result = {
            "ticker": stock.ticker,
            "name": stock.name,
            "alert_type": alert_type,
            "threshold": threshold,
            "current_price": current_price,
            "message": msg,
        }
        if extra:
            result.update(extra)

        logger.info(f"[알림 발화] {msg}")
        return result

    # ── 공개 체크 메서드 ───────────────────────────────────────────────────────

    def check_portfolio_alerts(self) -> list[dict]:
        """
        보유 종목의 현재가 vs 알림 임계값 비교.
        PriceAlert 미설정 시 AIRecommendation의 stop_loss/target_price로 fallback.

        Returns:
            발화된 알림 목록 [{"ticker", "name", "alert_type", "threshold", "current_price", "message"}]
        """
        triggered = []

        with get_db() as db:
            holdings = (
                db.query(PortfolioHolding, Stock)
                .join(Stock, PortfolioHolding.stock_id == Stock.id)
                .all()
            )

            for holding, stock in holdings:
                current_price = holding.current_price
                if current_price is None:
                    continue

                # 실제 PriceAlert ORM 레코드 조회
                orm_alerts: list[PriceAlert] = (
                    db.query(PriceAlert)
                    .filter(
                        and_(
                            PriceAlert.stock_id == stock.id,
                            PriceAlert.is_active == True,
                        )
                    )
                    .all()
                )

                # (condition, orm_alert_or_None) 쌍 목록 구성
                candidates: list[tuple] = [(a, a) for a in orm_alerts]

                # fallback: 최신 AI 추천의 stop_loss / target_price
                if not candidates:
                    latest_rec = (
                        db.query(AIRecommendation)
                        .filter(AIRecommendation.stock_id == stock.id)
                        .order_by(desc(AIRecommendation.recommendation_date))
                        .first()
                    )
                    if latest_rec:
                        if latest_rec.stop_loss:
                            candidates.append(
                                (_AlertCondition("STOP_LOSS", latest_rec.stop_loss), None)
                            )
                        if latest_rec.target_price:
                            candidates.append(
                                (_AlertCondition("TARGET_PRICE", latest_rec.target_price), None)
                            )

                for condition, orm_alert in candidates:
                    fired = False
                    if condition.alert_type == "STOP_LOSS" and current_price <= condition.threshold_value:
                        fired = True
                    elif condition.alert_type == "TARGET_PRICE" and current_price >= condition.threshold_value:
                        fired = True

                    if not fired:
                        continue

                    result = self._fire_alert(
                        db, stock, condition.alert_type,
                        current_price, condition.threshold_value,
                        orm_alert=orm_alert,
                    )
                    if result is not None:
                        triggered.append(result)

                # ── 트레일링 스톱 체크 (DB 변경 없이 코드 내 처리) ──
                # buy_date 이후 PriceHistory의 max(high)를 high_watermark로 사용
                buy_date = getattr(holding, "first_bought_at", None)
                if buy_date is None:
                    buy_date = getattr(holding, "created_at", None)

                if buy_date is not None and current_price is not None:
                    from sqlalchemy import func
                    high_watermark_row = (
                        db.query(func.max(PriceHistory.high))
                        .filter(
                            and_(
                                PriceHistory.stock_id == stock.id,
                                PriceHistory.interval == "1d",
                                PriceHistory.timestamp >= buy_date,
                            )
                        )
                        .scalar()
                    )

                    if high_watermark_row and high_watermark_row > 0:
                        # ATR 기반 동적 트레일링 스톱 계산
                        dynamic_pct = self.TRAILING_STOP_PCT  # 기본값 10%
                        try:
                            stock_for_atr = db.query(Stock).filter(Stock.ticker == stock.ticker).first()
                            if stock_for_atr:
                                ind_for_atr = db.query(TechnicalIndicator).filter(
                                    TechnicalIndicator.stock_id == stock_for_atr.id
                                ).order_by(TechnicalIndicator.date.desc()).first()
                                if ind_for_atr and hasattr(ind_for_atr, 'atr_14') and ind_for_atr.atr_14 and current_price > 0:
                                    dynamic_pct = (3 * ind_for_atr.atr_14) / current_price
                                    dynamic_pct = max(0.05, min(0.20, dynamic_pct))  # 5%~20% 범위
                        except Exception:
                            pass  # 실패시 기본 10% 사용

                        drawdown = (current_price - high_watermark_row) / high_watermark_row
                        if drawdown <= -dynamic_pct:
                            result = self._fire_alert(
                                db, stock, "TRAILING_STOP",
                                current_price, high_watermark_row,
                                extra={
                                    "high_watermark": round(high_watermark_row, 2),
                                    "drawdown_pct": round(drawdown * 100, 2),
                                },
                            )
                            if result is not None:
                                result["message"] = (
                                    f"[TRAILING_STOP] {stock.ticker} ({stock.name}) "
                                    f"현재가 ${current_price:.2f} / 최고가 ${high_watermark_row:.2f} "
                                    f"(하락률 {drawdown * 100:.1f}%)"
                                )
                                triggered.append(result)

        return triggered

    def check_volume_surge(self, threshold: float = 3.0) -> list[dict]:
        """
        watchlist 전체 오늘 거래량 vs volume_ma_20 비교.

        Args:
            threshold: 평균 대비 N배 이상이면 발화

        Returns:
            발화된 종목 목록
        """
        triggered = []
        today = self._now().date()

        with get_db() as db:
            stocks = db.query(Stock).filter(Stock.is_active == True).all()

            for stock in stocks:
                price_row = (
                    db.query(PriceHistory)
                    .filter(
                        and_(
                            PriceHistory.stock_id == stock.id,
                            PriceHistory.interval == "1d",
                        )
                    )
                    .order_by(desc(PriceHistory.timestamp))
                    .first()
                )
                if price_row is None or price_row.timestamp.date() != today:
                    continue

                indicator = (
                    db.query(TechnicalIndicator)
                    .filter(TechnicalIndicator.stock_id == stock.id)
                    .order_by(desc(TechnicalIndicator.date))
                    .first()
                )
                if indicator is None or not indicator.volume_ma_20:
                    continue

                if price_row.volume < indicator.volume_ma_20 * threshold:
                    continue

                ratio = price_row.volume / indicator.volume_ma_20
                surge_threshold = indicator.volume_ma_20 * threshold

                result = self._fire_alert(
                    db, stock, "VOLUME_SURGE",
                    price_row.close, surge_threshold,
                    extra={
                        "volume": price_row.volume,
                        "volume_ma20": indicator.volume_ma_20,
                        "ratio": round(ratio, 2),
                    },
                )
                if result is not None:
                    result["message"] = (
                        f"[VOLUME_SURGE] {stock.ticker} 거래량 {price_row.volume:,} "
                        f"(평균 대비 {ratio:.1f}배)"
                    )
                    triggered.append(result)

        return triggered

    def check_and_notify(self) -> bool:
        """
        전체 알림 체크 후 카카오 발송.
        카카오 미설정 시 로그만 출력(graceful).

        Returns:
            카카오 전송 성공 여부 (미설정 시 True)
        """
        portfolio_alerts = self.check_portfolio_alerts()
        volume_alerts = self.check_volume_surge()
        all_alerts = portfolio_alerts + volume_alerts

        if not all_alerts:
            logger.debug("[알림 매니저] 발화 조건 없음")
            return True

        logger.info(f"[알림 매니저] {len(all_alerts)}건 알림 발화")

        try:
            from notifications.kakao import kakao_notifier
            kakao_notifier.send_price_alerts(all_alerts)
        except Exception as e:
            logger.debug(f"[알림 매니저] 카카오 전송 스킵: {e}")
        try:
            from notifications.telegram import telegram_notifier
            telegram_notifier.send_price_alerts(all_alerts)
        except Exception as e:
            logger.debug(f"[알림 매니저] 텔레그램 전송 스킵: {e}")
        return True

    def get_alert_history(self, days: int = 7) -> list[dict]:
        """
        최근 N일 알림 발화 이력을 반환합니다.

        Returns:
            [{"ticker", "name", "alert_type", "trigger_price", "triggered_at", "message", "is_sent"}]
        """
        since = self._now() - timedelta(days=days)

        with get_db() as db:
            rows = (
                db.query(AlertHistory, Stock.ticker, Stock.name)
                .join(Stock, AlertHistory.stock_id == Stock.id)
                .filter(AlertHistory.triggered_at >= since)
                .order_by(desc(AlertHistory.triggered_at))
                .all()
            )

            return [
                {
                    "ticker": ticker,
                    "name": name,
                    "alert_type": ah.alert_type,
                    "trigger_price": ah.trigger_price,
                    "triggered_at": ah.triggered_at.strftime("%Y-%m-%d %H:%M"),
                    "message": ah.message,
                    "is_sent": ah.is_sent,
                }
                for ah, ticker, name in rows
            ]

    def set_alert(self, ticker: str, alert_type: str, threshold_value: float) -> bool:
        """
        알림 조건을 설정합니다. 기존 동일 유형 알림은 업데이트합니다.

        Args:
            ticker         : 종목 코드
            alert_type     : STOP_LOSS | TARGET_PRICE | VOLUME_SURGE
            threshold_value: 임계값 (가격 또는 배수)

        Returns:
            성공 여부
        """
        if alert_type not in VALID_ALERT_TYPES:
            logger.error(f"[알림 설정] 잘못된 alert_type: {alert_type}")
            return False

        try:
            with get_db() as db:
                stock = db.query(Stock).filter(Stock.ticker == ticker.upper()).first()
                if stock is None:
                    logger.error(f"[알림 설정] 종목을 찾을 수 없습니다: {ticker}")
                    return False

                existing = (
                    db.query(PriceAlert)
                    .filter(
                        and_(
                            PriceAlert.stock_id == stock.id,
                            PriceAlert.alert_type == alert_type,
                        )
                    )
                    .first()
                )

                if existing:
                    existing.threshold_value = threshold_value
                    existing.is_active = True
                    logger.info(f"[알림 설정] {ticker} {alert_type} 업데이트 → {threshold_value}")
                else:
                    db.add(PriceAlert(
                        stock_id=stock.id,
                        alert_type=alert_type,
                        threshold_value=threshold_value,
                        is_active=True,
                    ))
                    logger.info(f"[알림 설정] {ticker} {alert_type} 신규 등록 @ {threshold_value}")

            return True
        except Exception as e:
            logger.error(f"[알림 설정] 실패: {e}")
            return False


    def get_active_alerts(self) -> list[dict]:
        """
        현재 활성화된 모든 가격 알림을 반환합니다.

        Returns:
            [
                {
                    "ticker": str,
                    "name": str,
                    "alert_type": str,
                    "threshold_value": float,
                    "last_triggered_at": str | None,  # "YYYY-MM-DD HH:MM" 또는 None
                }
            ]
            ticker 오름차순 정렬
        """
        with get_db() as db:
            rows = (
                db.query(PriceAlert, Stock.ticker, Stock.name)
                .join(Stock, PriceAlert.stock_id == Stock.id)
                .filter(PriceAlert.is_active == True)
                .order_by(Stock.ticker.asc())
                .all()
            )

            return [
                {
                    "ticker": ticker,
                    "name": name,
                    "alert_type": alert.alert_type,
                    "threshold_value": alert.threshold_value,
                    "last_triggered_at": (
                        alert.last_triggered_at.strftime("%Y-%m-%d %H:%M")
                        if alert.last_triggered_at is not None
                        else None
                    ),
                }
                for alert, ticker, name in rows
            ]


# 싱글톤 인스턴스
alert_manager = AlertManager()
