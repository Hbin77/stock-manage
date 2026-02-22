"""
백테스팅 엔진
AI 추천 결과를 사후 검증하여 실제 수익률을 추적합니다.

로직:
  - AIRecommendation.outcome_return이 null인 레코드를 대상으로
  - 추천일 이후 5/10/30일 가격 데이터를 조회하여 수익률 계산
  - 결과를 DB에 저장하여 누적 성과 추적
"""
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import TypeAlias

from loguru import logger
from sqlalchemy import and_

from database.connection import get_db
from database.models import AIRecommendation, PriceHistory, Stock

# ── 타입 별칭 ──────────────────────────────────────────────────────────────────
LookbackWindows: TypeAlias = list[int]
GroupStats: TypeAlias = dict[str, float]          # {"win_rate": ..., "avg_return": ...}
AccuracyStats: TypeAlias = dict                   # get_accuracy_stats 반환 타입
ActionBreakdown: TypeAlias = list[dict]           # get_action_breakdown 반환 타입
MonthlyPerformance: TypeAlias = list[dict]        # get_monthly_performance 반환 타입
TopPerformers: TypeAlias = list[dict]             # get_top_performers 반환 타입


def _now() -> datetime:
    """UTC 기준 현재 시각을 tzinfo 없는 naive datetime으로 반환합니다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Backtester:
    """AI 추천 결과 사후 검증 엔진"""

    LOOKBACK_WINDOWS: LookbackWindows = [5, 10, 30]
    TRADING_COST: float = 0.003  # 0.3% = 수수료 0.1% + 슬리피지 0.2%

    # ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _group_stats(returns: list[float], trading_cost_pct: float = 0.3) -> GroupStats:
        """
        수익률 목록으로 승률과 평균 수익률을 계산합니다.

        Args:
            returns: 수익률 값 목록 (비어있으면 안 됨)
            trading_cost_pct: 수수료 이상 벌어야 승리로 인정 (기본 0.3%)

        Returns:
            {"win_rate": float, "avg_return": float}
        """
        # 수수료 이상 벌어야 실질 승리로 인정
        wins = [x for x in returns if x > trading_cost_pct]
        return {
            "win_rate": round(len(wins) / len(returns) * 100, 2),
            "avg_return": round(sum(returns) / len(returns), 4),
        }

    # ── 공개 메서드 ────────────────────────────────────────────────────────────

    def update_outcomes(self, lookback_windows: LookbackWindows | None = None) -> int:
        """
        outcome_return이 null인 AIRecommendation 레코드에 대해
        추천일 이후 가격 데이터를 조회하여 수익률을 계산합니다.

        Args:
            lookback_windows: 검증할 영업일 윈도우 목록 (기본: [5, 10, 30])

        Returns:
            업데이트된 레코드 수 (int)
        """
        windows = lookback_windows or self.LOOKBACK_WINDOWS
        today = _now()
        updated = 0

        with get_db() as db:
            pending = (
                db.query(AIRecommendation)
                .filter(
                    and_(
                        AIRecommendation.outcome_return == None,
                        AIRecommendation.price_at_recommendation != None,
                    )
                )
                .all()
            )

            logger.info(f"[백테스팅] 결과 미집계 추천 {len(pending)}건 처리 시작")

            for rec in pending:
                rec_date = rec.recommendation_date
                price_at_rec = rec.price_at_recommendation

                # 0 또는 음수 가격은 계산 불가 — 스킵
                if price_at_rec <= 0:
                    logger.warning(f"[백테스팅] 비정상 추천가 스킵: rec_id={rec.id} price={price_at_rec}")
                    continue

                # 모든 윈도우를 순회하며 가장 긴 기간의 수익률을 사용
                outcome_close = None
                for days in sorted(windows):
                    target_date = rec_date + timedelta(days=days)
                    if today < target_date:
                        continue

                    row = (
                        db.query(PriceHistory)
                        .filter(
                            and_(
                                PriceHistory.stock_id == rec.stock_id,
                                PriceHistory.interval == "1d",
                                PriceHistory.timestamp >= target_date,
                            )
                        )
                        .order_by(PriceHistory.timestamp.asc())
                        .first()
                    )
                    if row:
                        outcome_close = row.close

                if outcome_close is None:
                    continue

                outcome_return = ((outcome_close - price_at_rec) / price_at_rec - self.TRADING_COST) * 100
                rec.outcome_price = outcome_close
                rec.outcome_return = round(outcome_return, 4)
                updated += 1

            logger.success(f"[백테스팅] {updated}건 업데이트 완료")

        return updated

    def get_accuracy_stats(self, days: int = 90) -> AccuracyStats:
        """
        AI 추천 정확도 통계를 반환합니다.

        Args:
            days: 최근 N일 기간

        Returns:
            {
                "total_recommendations": int,
                "with_outcomes": int,
                "win_rate": float | None,
                "avg_return": float | None,
                "median_return": float | None,
                "best_ticker": str | None,
                "best_return": float | None,
                "worst_ticker": str | None,
                "worst_return": float | None,
                "sharpe_proxy": float | None,
            }
        """
        since = _now() - timedelta(days=days)

        with get_db() as db:
            recs = (
                db.query(AIRecommendation, Stock.ticker)
                .join(Stock, AIRecommendation.stock_id == Stock.id)
                .filter(AIRecommendation.recommendation_date >= since)
                .all()
            )

            total = len(recs)
            with_outcomes = [(r, t) for r, t in recs if r.outcome_return is not None]
            n_outcomes = len(with_outcomes)

            if n_outcomes == 0:
                return {
                    "total_recommendations": total,
                    "with_outcomes": 0,
                    "win_rate": None,
                    "avg_return": None,
                    "median_return": None,
                    "best_ticker": None,
                    "best_return": None,
                    "worst_ticker": None,
                    "worst_return": None,
                    "sharpe_proxy": None,
                }

            returns = [r.outcome_return for r, _ in with_outcomes]
            stats = self._group_stats(returns, trading_cost_pct=self.TRADING_COST * 100)
            med_return = median(returns)
            # TODO: SPY 벤치마크 대비 초과수익(alpha) 계산 추가
            # - 동일 기간 SPY 수익률 조회 후 alpha = avg_return - spy_return 산출

            # Sharpe proxy: avg / std (단순 근사)
            sharpe_proxy = None
            if n_outcomes > 1:
                avg_return = stats["avg_return"]
                variance = sum((x - avg_return) ** 2 for x in returns) / (n_outcomes - 1)
                std = variance ** 0.5
                sharpe_proxy = round(avg_return / std, 4) if std > 0 else None

            best = max(with_outcomes, key=lambda x: x[0].outcome_return)
            worst = min(with_outcomes, key=lambda x: x[0].outcome_return)

            return {
                "total_recommendations": total,
                "with_outcomes": n_outcomes,
                "win_rate": stats["win_rate"],
                "avg_return": stats["avg_return"],
                "median_return": round(med_return, 4),
                "best_ticker": best[1],
                "best_return": round(best[0].outcome_return, 4),
                "worst_ticker": worst[1],
                "worst_return": round(worst[0].outcome_return, 4),
                "sharpe_proxy": sharpe_proxy,
            }

    def get_action_breakdown(self, days: int = 90) -> ActionBreakdown:
        """
        액션(STRONG_BUY/BUY/HOLD)별 성과 분석을 반환합니다.

        Args:
            days: 최근 N일 기간

        Returns:
            [{"action": str, "count": int, "win_rate": float, "avg_return": float}]
        """
        since = _now() - timedelta(days=days)

        with get_db() as db:
            recs = (
                db.query(AIRecommendation)
                .filter(
                    and_(
                        AIRecommendation.recommendation_date >= since,
                        AIRecommendation.outcome_return != None,
                    )
                )
                .all()
            )

        groups: dict[str, list[float]] = {}
        for r in recs:
            groups.setdefault(r.action, []).append(r.outcome_return)

        result = []
        for action in ["STRONG_BUY", "BUY", "HOLD"]:
            returns = groups.get(action, [])
            if not returns:
                continue
            result.append({"action": action, "count": len(returns), **self._group_stats(returns)})

        return result

    def get_monthly_performance(self, months: int = 6) -> MonthlyPerformance:
        """
        월별 AI 추천 성과를 반환합니다.

        Args:
            months: 최근 N개월

        Returns:
            [{"month": str, "count": int, "win_rate": float, "avg_return": float}]
            month 형식: "YYYY-MM", 오름차순 정렬
        """
        since = _now() - timedelta(days=months * 31)

        with get_db() as db:
            recs = (
                db.query(AIRecommendation)
                .filter(
                    and_(
                        AIRecommendation.recommendation_date >= since,
                        AIRecommendation.outcome_return != None,
                    )
                )
                .all()
            )

        monthly: dict[str, list[float]] = {}
        for r in recs:
            month_key = r.recommendation_date.strftime("%Y-%m")
            monthly.setdefault(month_key, []).append(r.outcome_return)

        return [
            {"month": month, "count": len(returns), **self._group_stats(returns)}
            for month in sorted(monthly.keys())
            for returns in [monthly[month]]
        ]


    def get_top_performers(self, n: int = 5) -> TopPerformers:
        """
        outcome_return 기준 상위 N개 AI 추천 결과를 반환합니다.

        Args:
            n: 반환할 최대 레코드 수 (기본: 5)

        Returns:
            [
                {
                    "ticker": str,
                    "name": str,
                    "action": str,
                    "recommendation_date": str,   # "YYYY-MM-DD" 형식
                    "outcome_return": float,
                    "price_at_recommendation": float | None,
                }
            ]
            outcome_return 내림차순 정렬
        """
        with get_db() as db:
            rows = (
                db.query(AIRecommendation, Stock.ticker, Stock.name)
                .join(Stock, AIRecommendation.stock_id == Stock.id)
                .filter(AIRecommendation.outcome_return != None)
                .order_by(AIRecommendation.outcome_return.desc())
                .limit(n)
                .all()
            )

            return [
                {
                    "ticker": ticker,
                    "name": name,
                    "action": rec.action,
                    "recommendation_date": rec.recommendation_date.strftime("%Y-%m-%d"),
                    "outcome_return": round(rec.outcome_return, 4),
                    "price_at_recommendation": rec.price_at_recommendation,
                }
                for rec, ticker, name in rows
            ]


# 싱글톤 인스턴스
backtester = Backtester()
