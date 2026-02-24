"""리스크 관리 엔진 - 포지션 사이징, 섹터 분산, 최대 손실 관리"""
import os

from loguru import logger
from config.settings import settings


class RiskManager:
    # 리스크 파라미터 (환경변수로 설정 가능)
    MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.10"))
    MAX_HOLDINGS = int(os.getenv("MAX_HOLDINGS", "30"))
    MAX_SECTOR_PCT = float(os.getenv("MAX_SECTOR_PCT", "0.40"))
    MAX_PORTFOLIO_LOSS_PCT = float(os.getenv("MAX_PORTFOLIO_LOSS_PCT", "-0.15"))

    def check_can_buy(self, ticker: str, sector: str = None) -> dict:
        """매수 가능 여부를 리스크 관점에서 판단합니다.

        Returns:
            {"allowed": bool, "reason": str, "max_amount_pct": float}
        """
        from database.connection import get_db
        from database.models import PortfolioHolding, Stock

        with get_db() as db:
            # 1. 현재 보유 종목 수 확인 (단일 JOIN 쿼리로 Stock 일괄 로드)
            rows = (
                db.query(PortfolioHolding, Stock)
                .join(Stock, PortfolioHolding.stock_id == Stock.id)
                .filter(PortfolioHolding.quantity > 0)
                .all()
            )
            holdings = [h for h, _ in rows]
            stock_map = {h.stock_id: s for h, s in rows}

            if len(holdings) >= self.MAX_HOLDINGS:
                return {"allowed": False, "reason": f"최대 보유 종목 수({self.MAX_HOLDINGS}) 초과", "max_amount_pct": 0}

            # 2. 이미 보유 중인 종목인지 확인 (경고만, 차단 안함)
            for h in holdings:
                stock = stock_map.get(h.stock_id)
                if stock and stock.ticker == ticker:
                    logger.warning(f"[리스크] {ticker} 이미 보유 중 — 추가 매수 경고 (차단 안함)")
                    break

            # 3. 섹터 집중도 확인 (종목 수 기반)
            if sector:
                sector_count = 0
                for h in holdings:
                    stock = stock_map.get(h.stock_id)
                    if stock and stock.sector == sector:
                        sector_count += 1
                # 섹터당 최대 5종목 (MAX_HOLDINGS의 1/3)
                max_per_sector = max(3, self.MAX_HOLDINGS // 3)
                if sector_count >= max_per_sector:
                    return {"allowed": False, "reason": f"섹터({sector}) 집중도 초과 ({sector_count}개)", "max_amount_pct": 0}

            # 4. 섹터 집중도 확인 (금액 비중 기반)
            if sector:
                total_value = 0
                sector_value = 0
                for h in holdings:
                    stock_h = stock_map.get(h.stock_id)
                    holding_value = (h.quantity or 0) * (h.current_price or h.avg_buy_price or 0)
                    total_value += holding_value
                    if stock_h and stock_h.sector == sector:
                        sector_value += holding_value

                if total_value > 0:
                    sector_pct = sector_value / total_value
                    if sector_pct >= self.MAX_SECTOR_PCT:
                        return {"allowed": False, "reason": f"섹터({sector}) 금액 비중 {sector_pct:.0%} >= {self.MAX_SECTOR_PCT:.0%}", "max_amount_pct": 0}

            # 5. 포트폴리오 일일 손실 한도 체크
            total_value = sum(
                (h.quantity or 0) * (h.current_price or h.avg_buy_price or 0)
                for h in holdings
            )
            total_invested = sum((h.total_invested or 0) for h in holdings)
            if total_invested > 0:
                portfolio_return = (total_value - total_invested) / total_invested
                if portfolio_return <= self.MAX_PORTFOLIO_LOSS_PCT:
                    return {
                        "allowed": False,
                        "reason": f"포트폴리오 손실 {portfolio_return:.1%}이 한도 {self.MAX_PORTFOLIO_LOSS_PCT:.1%} 초과",
                        "max_amount_pct": 0,
                    }

            return {
                "allowed": True,
                "reason": "매수 가능",
                "max_amount_pct": self.MAX_POSITION_PCT,
                "current_holdings": len(holdings),
                "remaining_slots": self.MAX_HOLDINGS - len(holdings),
            }

    def get_portfolio_risk_summary(self) -> dict:
        """포트폴리오 전체 리스크 요약을 반환합니다."""
        from database.connection import get_db
        from database.models import PortfolioHolding, Stock

        with get_db() as db:
            rows = (
                db.query(PortfolioHolding, Stock)
                .join(Stock, PortfolioHolding.stock_id == Stock.id)
                .filter(PortfolioHolding.quantity > 0)
                .all()
            )

            sector_counts = {}
            for h, stock in rows:
                sector = stock.sector or "Unknown"
                sector_counts[sector] = sector_counts.get(sector, 0) + 1

            return {
                "total_holdings": len(rows),
                "max_holdings": self.MAX_HOLDINGS,
                "sector_distribution": sector_counts,
                "max_position_pct": self.MAX_POSITION_PCT,
            }


risk_manager = RiskManager()
