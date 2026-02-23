"""
포트폴리오 관리 모듈
보유 종목의 매수/매도 기록과 손익 계산을 담당합니다.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import desc

from database.connection import get_db
from database.models import PortfolioHolding, Stock, Transaction
from data_fetcher.market_data import market_fetcher


class PortfolioManager:
    """
    포트폴리오 CRUD 및 손익 계산 매니저

    주요 기능:
      - 매수/매도 거래 기록
      - 보유 종목 평가손익 실시간 계산
      - 포트폴리오 전체 현황 요약
    """

    # ─────────────────────────────────────────
    # 매수 기록
    # ─────────────────────────────────────────
    def buy(
        self,
        ticker: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        note: Optional[str] = None,
        executed_at: Optional[datetime] = None,
    ) -> Transaction:
        """
        매수 거래를 기록하고 보유 종목 정보를 업데이트합니다.

        Args:
            ticker     : 종목 코드
            quantity   : 매수 수량
            price      : 매수 단가
            fee        : 수수료
            note       : 메모 (AI 추천 근거 등)
            executed_at: 체결 시각 (없으면 현재 시각)
        """
        if quantity <= 0 or price <= 0:
            raise ValueError("수량과 가격은 0보다 커야 합니다.")

        executed_at = executed_at or datetime.now(timezone.utc).replace(tzinfo=None)
        total_amount = quantity * price + fee

        with get_db() as db:
            # 종목 조회 / 등록
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                stock = market_fetcher.sync_stock_info(ticker, db)
            if stock is None:
                raise ValueError(f"종목을 찾을 수 없습니다: {ticker}")

            # 거래 내역 저장
            tx = Transaction(
                stock_id=stock.id,
                action="BUY",
                quantity=quantity,
                price=price,
                total_amount=total_amount,
                fee=fee,
                note=note,
                executed_at=executed_at,
            )
            db.add(tx)

            # 보유 현황 업데이트
            holding = (
                db.query(PortfolioHolding)
                .filter(PortfolioHolding.stock_id == stock.id)
                .first()
            )
            if holding is None:
                holding = PortfolioHolding(
                    stock_id=stock.id,
                    quantity=quantity,
                    avg_buy_price=price,
                    total_invested=total_amount,
                    first_bought_at=executed_at,
                )
                db.add(holding)
            else:
                # 평균 매수가 재계산 (기존 투자금 + 신규 투자금) / 총 수량
                new_quantity = holding.quantity + quantity
                new_invested = holding.total_invested + total_amount
                holding.avg_buy_price = new_invested / new_quantity
                holding.quantity = new_quantity
                holding.total_invested = new_invested

            db.flush()
            logger.success(
                f"[매수] {ticker} {quantity}주 @ ${price:.2f} "
                f"(총 ${total_amount:.2f}, 수수료 ${fee:.2f})"
            )
            return tx

    # ─────────────────────────────────────────
    # 매도 기록
    # ─────────────────────────────────────────
    def sell(
        self,
        ticker: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        note: Optional[str] = None,
        executed_at: Optional[datetime] = None,
    ) -> Transaction:
        """
        매도 거래를 기록하고 실현 손익을 계산합니다.

        Args:
            ticker     : 종목 코드
            quantity   : 매도 수량
            price      : 매도 단가
            fee        : 수수료
            note       : 메모
            executed_at: 체결 시각
        """
        executed_at = executed_at or datetime.now(timezone.utc).replace(tzinfo=None)
        total_amount = quantity * price - fee

        with get_db() as db:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                raise ValueError(f"종목을 찾을 수 없습니다: {ticker}")

            holding = (
                db.query(PortfolioHolding)
                .filter(PortfolioHolding.stock_id == stock.id)
                .first()
            )
            if holding is None or holding.quantity < quantity:
                raise ValueError(
                    f"[{ticker}] 보유 수량 부족 "
                    f"(보유: {holding.quantity if holding else 0}, 매도 요청: {quantity})"
                )

            # 실현 손익 = 매도금액 - (평균 매수가 × 수량) - 수수료
            realized_pnl = total_amount - (holding.avg_buy_price * quantity)

            # 거래 내역 저장
            tx = Transaction(
                stock_id=stock.id,
                action="SELL",
                quantity=quantity,
                price=price,
                total_amount=total_amount,
                fee=fee,
                realized_pnl=realized_pnl,
                note=note,
                executed_at=executed_at,
            )
            db.add(tx)

            # 보유 현황 업데이트
            holding.quantity -= quantity
            holding.total_invested -= holding.avg_buy_price * quantity

            if holding.quantity <= 0:
                # 전량 매도 → 보유 종목 삭제
                db.delete(holding)
                logger.info(f"[{ticker}] 전량 매도 완료, 보유 목록에서 제거")
            else:
                holding.total_invested = max(holding.total_invested, 0)

            db.flush()
            logger.success(
                f"[매도] {ticker} {quantity}주 @ ${price:.2f} "
                f"| 실현손익: ${realized_pnl:+.2f}"
            )
            return tx

    # ─────────────────────────────────────────
    # 보유 현황 조회
    # ─────────────────────────────────────────
    def get_holdings(self, update_prices: bool = True) -> list[dict]:
        """
        현재 보유 종목 목록과 평가손익을 반환합니다.

        Args:
            update_prices: True이면 실시간 가격으로 손익 갱신
        """
        results = []

        with get_db() as db:
            rows = (
                db.query(PortfolioHolding, Stock)
                .join(Stock, PortfolioHolding.stock_id == Stock.id)
                .all()
            )

            for h, stock in rows:

                current_price = h.current_price or h.avg_buy_price

                if update_prices:
                    price_data = market_fetcher.fetch_realtime_price(stock.ticker)
                    if price_data:
                        current_price = price_data["price"]
                        h.current_price = current_price

                current_value = current_price * h.quantity
                unrealized_pnl = current_value - h.total_invested
                unrealized_pnl_pct = (
                    (unrealized_pnl / h.total_invested * 100) if h.total_invested else 0.0
                )

                h.unrealized_pnl = unrealized_pnl
                h.unrealized_pnl_pct = unrealized_pnl_pct

                results.append({
                    "ticker": stock.ticker,
                    "name": stock.name,
                    "quantity": h.quantity,
                    "avg_buy_price": h.avg_buy_price,
                    "current_price": current_price,
                    "total_invested": h.total_invested,
                    "current_value": current_value,
                    "unrealized_pnl": unrealized_pnl,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "first_bought_at": h.first_bought_at.strftime("%Y-%m-%d"),
                })

        return sorted(results, key=lambda x: x["unrealized_pnl_pct"], reverse=True)

    def get_summary(self) -> dict:
        """포트폴리오 전체 요약 정보를 반환합니다."""
        holdings = self.get_holdings(update_prices=True)

        total_invested = sum(h["total_invested"] for h in holdings)
        total_value = sum(h["current_value"] for h in holdings)
        total_pnl = total_value - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested else 0.0

        return {
            "total_holdings": len(holdings),
            "total_invested": total_invested,
            "total_value": total_value,
            "total_unrealized_pnl": total_pnl,
            "total_unrealized_pnl_pct": total_pnl_pct,
            "holdings": holdings,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def get_transaction_history(self, days: int = 365) -> list[dict]:
        """
        거래 이력을 반환합니다.

        Args:
            days: 최근 N일

        Returns:
            [{"ticker", "name", "action", "quantity", "price", "total_amount",
              "fee", "realized_pnl", "note", "executed_at"}]
        """
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

        with get_db() as db:
            rows = (
                db.query(Transaction, Stock.ticker, Stock.name)
                .join(Stock, Transaction.stock_id == Stock.id)
                .filter(Transaction.executed_at >= since)
                .order_by(desc(Transaction.executed_at))
                .all()
            )

            return [
                {
                    "ticker": ticker,
                    "name": name,
                    "action": tx.action,
                    "quantity": tx.quantity,
                    "price": tx.price,
                    "total_amount": tx.total_amount,
                    "fee": tx.fee,
                    "realized_pnl": tx.realized_pnl,
                    "note": tx.note,
                    "executed_at": tx.executed_at.strftime("%Y-%m-%d %H:%M"),
                }
                for tx, ticker, name in rows
            ]

    def get_realized_pnl_by_period(self) -> dict:
        """
        SELL 거래의 realized_pnl을 월별 집계합니다.

        Returns:
            {
                "monthly": [{"month": "2025-09", "realized_pnl": float, "trade_count": int}],
                "total_realized": float
            }
        """
        with get_db() as db:
            sells = (
                db.query(Transaction)
                .filter(
                    Transaction.action == "SELL",
                    Transaction.realized_pnl != None,
                )
                .order_by(Transaction.executed_at.asc())
                .all()
            )

        monthly: dict[str, dict] = {}
        total_realized = 0.0

        for tx in sells:
            month_key = tx.executed_at.strftime("%Y-%m")
            if month_key not in monthly:
                monthly[month_key] = {"realized_pnl": 0.0, "trade_count": 0}
            monthly[month_key]["realized_pnl"] += tx.realized_pnl or 0.0
            monthly[month_key]["trade_count"] += 1
            total_realized += tx.realized_pnl or 0.0

        monthly_list = [
            {"month": k, "realized_pnl": round(v["realized_pnl"], 4), "trade_count": v["trade_count"]}
            for k, v in sorted(monthly.items())
        ]

        return {
            "monthly": monthly_list,
            "total_realized": round(total_realized, 4),
        }

    def get_sector_allocation(self) -> list[dict]:
        """
        보유 종목의 섹터별 투자 비중을 반환합니다.

        Returns:
            [{"sector": str, "value": float, "pct": float}] 내림차순
        """
        holdings = self.get_holdings(update_prices=False)
        if not holdings:
            return []

        total_value = sum(h["current_value"] for h in holdings)
        if total_value == 0:
            return []

        # 단일 쿼리로 보유 종목 전체 섹터 일괄 조회
        tickers = [h["ticker"] for h in holdings]
        ticker_sectors: dict[str, str] = {}

        with get_db() as db:
            stocks = db.query(Stock).filter(Stock.ticker.in_(tickers)).all()
            for stock in stocks:
                ticker_sectors[stock.ticker] = stock.sector if stock.sector else "Unknown"

        # 조회되지 않은 티커는 "Unknown" 처리
        for ticker in tickers:
            ticker_sectors.setdefault(ticker, "Unknown")

        # 섹터별 가치 집계
        sector_map: dict[str, float] = {}
        for h in holdings:
            sector = ticker_sectors[h["ticker"]]
            sector_map[sector] = sector_map.get(sector, 0.0) + h["current_value"]

        return sorted(
            [
                {
                    "sector": sector,
                    "value": round(value, 2),
                    "pct": round(value / total_value * 100, 2),
                }
                for sector, value in sector_map.items()
            ],
            key=lambda x: x["value"],
            reverse=True,
        )

    # ─────────────────────────────────────────
    # 종목 삭제 (포트폴리오에서 제거)
    # ─────────────────────────────────────────
    def delete_holding(self, ticker: str) -> bool:
        """
        보유 종목을 포트폴리오에서 완전히 삭제합니다.
        거래 내역(Transaction)은 보존하고, 보유 현황(PortfolioHolding)과
        관련 알림(PriceAlert)만 삭제합니다.

        Args:
            ticker: 종목 코드

        Returns:
            True: 삭제 성공, False: 종목 미보유
        """
        with get_db() as db:
            stock = db.query(Stock).filter(Stock.ticker == ticker).first()
            if stock is None:
                logger.warning(f"[삭제] 종목을 찾을 수 없음: {ticker}")
                return False

            holding = (
                db.query(PortfolioHolding)
                .filter(PortfolioHolding.stock_id == stock.id)
                .first()
            )
            if holding is None:
                logger.warning(f"[삭제] 보유하지 않은 종목: {ticker}")
                return False

            # 관련 알림 삭제
            try:
                from database.models import PriceAlert
                db.query(PriceAlert).filter(PriceAlert.stock_id == stock.id).delete()
            except Exception:
                pass

            db.delete(holding)
            logger.success(
                f"[삭제] {ticker} ({stock.name}) 포트폴리오에서 제거 완료 "
                f"(수량: {holding.quantity}주, 투자금: ${holding.total_invested:.2f})"
            )
            return True

    def print_summary(self) -> None:
        """포트폴리오 현황을 콘솔에 출력합니다."""
        summary = self.get_summary()
        pnl_sign = "+" if summary["total_unrealized_pnl"] >= 0 else ""

        print("\n" + "=" * 60)
        print("  포트폴리오 현황")
        print("=" * 60)
        print(f"  보유 종목 수  : {summary['total_holdings']}개")
        print(f"  총 투자금액   : ${summary['total_invested']:>12,.2f}")
        print(f"  현재 평가금액 : ${summary['total_value']:>12,.2f}")
        print(
            f"  평가 손익     : ${pnl_sign}{summary['total_unrealized_pnl']:>11,.2f} "
            f"({pnl_sign}{summary['total_unrealized_pnl_pct']:.2f}%)"
        )
        print("-" * 60)

        for h in summary["holdings"]:
            sign = "+" if h["unrealized_pnl"] >= 0 else ""
            print(
                f"  [{h['ticker']:<10}] {h['name'][:20]:<20} "
                f"{h['quantity']:>6.1f}주 | "
                f"평균매수 ${h['avg_buy_price']:>8.2f} | "
                f"현재가 ${h['current_price']:>8.2f} | "
                f"{sign}{h['unrealized_pnl_pct']:.2f}%"
            )

        print("=" * 60)
        print(f"  기준 시각: {summary['updated_at']}")
        print("=" * 60 + "\n")


# 싱글톤 인스턴스
portfolio_manager = PortfolioManager()
