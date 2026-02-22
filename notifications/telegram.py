"""
텔레그램 봇 알림 모듈
텔레그램 Bot API를 사용하여 푸시 알림을 전송합니다.

설정:
  .env 파일에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 추가
"""
import time

import requests
from loguru import logger

from config.settings import settings

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """텔레그램 봇 알림 전송"""

    def _is_configured(self) -> bool:
        return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)

    def _send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """텔레그램 메시지를 전송합니다. 429/네트워크 오류 시 최대 3회 재시도."""
        if not self._is_configured():
            logger.debug("[텔레그램] TELEGRAM_BOT_TOKEN 또는 CHAT_ID 미설정, 스킵")
            return False

        for attempt in range(3):
            try:
                resp = requests.post(
                    TELEGRAM_API_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
                    json={
                        "chat_id": settings.TELEGRAM_CHAT_ID,
                        "text": text,
                        "parse_mode": parse_mode,
                    },
                    timeout=10,
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    return True
                elif resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                    logger.warning(f"[텔레그램] Rate limit, {retry_after}초 후 재시도")
                    time.sleep(retry_after)
                    continue
                else:
                    logger.error(f"[텔레그램] 전송 실패: {resp.status_code} {resp.text[:200]}")
                    return False

            except requests.exceptions.RequestException as e:
                if attempt < 2:
                    logger.warning(f"[텔레그램] 네트워크 오류 (시도 {attempt+1}/3): {e}")
                    time.sleep(2)
                else:
                    logger.error(f"[텔레그램] 전송 최종 실패: {e}")
                    return False
        return False

    # -- 공개 메서드 (카카오와 동일 인터페이스) --

    def send_buy_recommendations(self, recommendations: list[dict]) -> bool:
        buy_recs = [r for r in recommendations if r.get("action") in ("BUY", "STRONG_BUY")]
        if not buy_recs:
            return True

        lines = [f"*AI 매수 추천 ({len(buy_recs)}개)*\n"]
        for r in buy_recs[:10]:
            icon = "🟢🟢" if r["action"] == "STRONG_BUY" else "🟢"
            conf = int(r["confidence"] * 100)
            price = f"${r['price_at_recommendation']:.2f}" if r.get("price_at_recommendation") else "N/A"
            lines.append(f"{icon} *{r['ticker']}* ({conf}%) | {price}")

        success = self._send_message("\n".join(lines))
        if success:
            logger.info(f"[텔레그램] 매수 추천 알림 전송 완료 ({len(buy_recs)}개)")
        return success

    def send_sell_signals(self, sell_signals: list[dict]) -> bool:
        active = [s for s in sell_signals if s.get("signal") in ("SELL", "STRONG_SELL")]
        if not active:
            return True

        urgency_order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
        active.sort(key=lambda x: urgency_order.get(x.get("urgency", "LOW"), 2))

        lines = [f"*AI 매도 신호 ({len(active)}개)*\n"]
        for s in active[:10]:
            icon = {"HIGH": "🔴", "NORMAL": "🟠", "LOW": "🟡"}.get(s.get("urgency"), "🟡")
            pnl = s.get("current_pnl_pct", 0) or 0
            lines.append(f"{icon} *{s['ticker']}* ({pnl:+.1f}%) | {s.get('reasoning', '')[:50]}")

        success = self._send_message("\n".join(lines))
        if success:
            logger.info(f"[텔레그램] 매도 신호 알림 전송 완료 ({len(active)}개)")
        return success

    def send_daily_summary(self) -> bool:
        from portfolio.portfolio_manager import portfolio_manager
        try:
            summary = portfolio_manager.get_summary()
        except Exception as e:
            logger.error(f"[텔레그램] 포트폴리오 조회 실패: {e}")
            return False

        total_pnl = summary.get("total_unrealized_pnl", 0)
        total_pct = summary.get("total_unrealized_pnl_pct", 0)
        sign = "+" if total_pnl >= 0 else ""
        icon = "📈" if total_pnl >= 0 else "📉"

        lines = [f"{icon} *오늘의 포트폴리오 요약*\n"]
        lines.append(f"보유: {summary.get('total_holdings', 0)}개 종목")
        lines.append(f"평가손익: {sign}${total_pnl:,.0f} ({sign}{total_pct:.2f}%)\n")

        for h in summary.get("holdings", [])[:5]:
            s = "+" if h["unrealized_pnl_pct"] >= 0 else ""
            lines.append(f"  {h['ticker']}: {s}{h['unrealized_pnl_pct']:.1f}%")

        success = self._send_message("\n".join(lines))
        if success:
            logger.info("[텔레그램] 일일 포트폴리오 요약 전송 완료")
        return success

    def send_price_alerts(self, alerts: list[dict]) -> bool:
        if not alerts:
            return True
        if not self._is_configured():
            return True

        icon_map = {"STOP_LOSS": "🔴", "TARGET_PRICE": "🎯", "VOLUME_SURGE": "📊"}
        lines = [f"*가격 알림 ({len(alerts)}건)*\n"]
        for a in alerts[:10]:
            icon = icon_map.get(a.get("alert_type", ""), "⚠️")
            price = f"${a['current_price']:.2f}" if a.get("current_price") else "N/A"
            lines.append(f"{icon} *{a['ticker']}* {a.get('alert_type', '')} | 현재 {price}")

        success = self._send_message("\n".join(lines))
        if success:
            logger.info(f"[텔레그램] 가격 알림 전송 완료 ({len(alerts)}건)")
        return success

    def test_connection(self) -> bool:
        if not self._is_configured():
            logger.warning("[텔레그램] TELEGRAM_BOT_TOKEN 또는 CHAT_ID가 미설정입니다.")
            return False
        return self._send_message(
            "✅ 주식 관리 시스템 텔레그램 연결 테스트 성공!\n"
            "AI 매수/매도 추천 알림이 이 채널로 전송됩니다."
        )


# 싱글톤 인스턴스
telegram_notifier = TelegramNotifier()
