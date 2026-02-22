"""리스크 관리 엔진 - 포지션 사이징, 섹터 분산, 최대 손실 관리"""
from loguru import logger
from config.settings import settings


class RiskManager:
    # 리스크 파라미터 (향후 .env로 이동 가능)
    MAX_POSITION_PCT = 0.10        # 포지션별 최대 비중 10%
    MAX_HOLDINGS = 15              # 최대 동시 보유 종목 수
    MAX_SECTOR_PCT = 0.30          # 섹터별 최대 비중 30%
    MAX_PORTFOLIO_LOSS_PCT = -0.05 # 포트폴리오 일일 최대 손실 -5%

    def check_can_buy(self, ticker: str, sector: str = None) -> dict:
        """매수 가능 여부를 리스크 관점에서 판단합니다.

        Returns:
            {"allowed": bool, "reason": str, "max_amount_pct": float}
        """
        from database.connection import get_db
        from database.models import PortfolioHolding, Stock

        with get_db() as db:
            # 1. 현재 보유 종목 수 확인
            holdings = db.query(PortfolioHolding).filter(
                PortfolioHolding.quantity > 0
            ).all()

            if len(holdings) >= self.MAX_HOLDINGS:
                return {"allowed": False, "reason": f"최대 보유 종목 수({self.MAX_HOLDINGS}) 초과", "max_amount_pct": 0}

            # 2. 이미 보유 중인 종목인지 확인
            for h in holdings:
                stock = db.query(Stock).filter(Stock.id == h.stock_id).first()
                if stock and stock.ticker == ticker:
                    return {"allowed": False, "reason": f"이미 보유 중인 종목", "max_amount_pct": 0}

            # 3. 섹터 집중도 확인
            if sector:
                sector_count = 0
                for h in holdings:
                    stock = db.query(Stock).filter(Stock.id == h.stock_id).first()
                    if stock and stock.sector == sector:
                        sector_count += 1
                # 섹터당 최대 5종목 (MAX_HOLDINGS의 1/3)
                max_per_sector = max(3, self.MAX_HOLDINGS // 3)
                if sector_count >= max_per_sector:
                    return {"allowed": False, "reason": f"섹터({sector}) 집중도 초과 ({sector_count}개)", "max_amount_pct": 0}

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
            holdings = db.query(PortfolioHolding).filter(
                PortfolioHolding.quantity > 0
            ).all()

            sector_counts = {}
            for h in holdings:
                stock = db.query(Stock).filter(Stock.id == h.stock_id).first()
                if stock:
                    sector = stock.sector or "Unknown"
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1

            return {
                "total_holdings": len(holdings),
                "max_holdings": self.MAX_HOLDINGS,
                "sector_distribution": sector_counts,
                "max_position_pct": self.MAX_POSITION_PCT,
            }


risk_manager = RiskManager()
