"""
카카오톡 알림 모듈
카카오 REST API를 사용하여 나에게 보내기 메시지를 전송합니다.

초기 토큰 발급 절차 (1회):
  1. developers.kakao.com → 앱 생성 → REST API 키 획득
  2. 카카오 로그인 활성화 → 동의항목 "카카오톡 메시지 전송" 설정
  3. 브라우저 접속:
     https://kauth.kakao.com/oauth/authorize?client_id={KEY}&redirect_uri=http://localhost&response_type=code
  4. 리다이렉트 URL에서 code 파라미터 추출
  5. curl 또는 requests로 access_token + refresh_token 교환
  6. .env에 KAKAO_ACCESS_TOKEN, KAKAO_REFRESH_TOKEN 저장
"""
import requests
from loguru import logger

from config.settings import settings

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoNotifier:
    """카카오톡 나에게 보내기 알림 전송"""

    def _is_configured(self) -> bool:
        """카카오 설정 여부 확인"""
        return bool(settings.KAKAO_ACCESS_TOKEN)

    def _get_headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.KAKAO_ACCESS_TOKEN}"}

    def _refresh_access_token(self) -> bool:
        """Refresh Token으로 Access Token을 갱신합니다."""
        if not settings.KAKAO_REFRESH_TOKEN:
            logger.error("[카카오] Refresh Token이 없습니다. 수동으로 토큰을 재발급하세요.")
            return False
        if not settings.KAKAO_REST_API_KEY:
            logger.error("[카카오] KAKAO_REST_API_KEY가 설정되지 않았습니다.")
            return False

        try:
            resp = requests.post(
                KAKAO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.KAKAO_REST_API_KEY,
                    "refresh_token": settings.KAKAO_REFRESH_TOKEN,
                },
                timeout=10,
            )
            resp.raise_for_status()
            token_data = resp.json()
            new_token = token_data.get("access_token")
            if not new_token:
                logger.error(f"[카카오] 토큰 갱신 실패: {token_data}")
                return False

            # 런타임에서 settings 값 업데이트 (재시작 전까지 유효)
            settings.KAKAO_ACCESS_TOKEN = new_token
            if token_data.get("refresh_token"):
                settings.KAKAO_REFRESH_TOKEN = token_data["refresh_token"]

            logger.info("[카카오] Access Token 갱신 완료. .env 파일을 업데이트하세요.")
            logger.info(f"  새 Access Token: {new_token[:20]}...")
            return True

        except Exception as e:
            logger.error(f"[카카오] 토큰 갱신 요청 실패: {e}")
            return False

    def _send_message(self, template: dict, retry: bool = True) -> bool:
        """카카오 메시지를 전송합니다. 401 시 자동으로 토큰 갱신 후 재시도."""
        if not self._is_configured():
            logger.debug("[카카오] KAKAO_ACCESS_TOKEN 미설정, 알림 스킵")
            return False

        try:
            resp = requests.post(
                KAKAO_SEND_URL,
                headers=self._get_headers(),
                data={"template_object": str(template).replace("'", '"')},
                timeout=10,
            )

            if resp.status_code == 401 and retry:
                logger.warning("[카카오] 401 Unauthorized — 토큰 갱신 시도")
                if self._refresh_access_token():
                    return self._send_message(template, retry=False)
                return False

            if resp.status_code == 200:
                result = resp.json()
                if result.get("result_code") == 0:
                    return True
                logger.error(f"[카카오] 전송 실패: {result}")
                return False

            logger.error(f"[카카오] HTTP {resp.status_code}: {resp.text[:200]}")
            return False

        except Exception as e:
            logger.error(f"[카카오] 전송 중 오류: {e}")
            return False

    # ── 템플릿 빌더 ────────────────────────────────────────────────────────────

    def _build_buy_recommendation_template(self, recommendations: list[dict]) -> dict:
        """매수 추천 ListTemplate을 생성합니다."""
        items = []
        for r in recommendations[:5]:  # 최대 5건
            action_icon = "🟢🟢" if r["action"] == "STRONG_BUY" else "🟢"
            confidence_pct = int(r["confidence"] * 100)
            price_str = f"${r['price_at_recommendation']:.2f}" if r.get("price_at_recommendation") else "N/A"
            items.append({
                "title": f"{action_icon} {r['ticker']} ({confidence_pct}%)",
                "description": f"{r['name']} | {price_str}",
            })

        count = len(recommendations)
        return {
            "object_type": "list",
            "header_title": f"📈 AI 매수 추천 ({count}개)",
            "header_link": {"type": ""},
            "contents": items,
            "buttons": [],
        }

    def _build_sell_signal_template(self, sell_signals: list[dict]) -> dict:
        """매도 신호 ListTemplate을 생성합니다. urgency=HIGH 우선."""
        urgency_order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
        sorted_signals = sorted(sell_signals, key=lambda x: urgency_order.get(x.get("urgency", "LOW"), 2))

        items = []
        for s in sorted_signals[:5]:
            urgency_icon = {"HIGH": "🔴", "NORMAL": "🟠", "LOW": "🟡"}.get(s.get("urgency", "NORMAL"), "🟡")
            signal_icon = "📉📉" if s["signal"] == "STRONG_SELL" else "📉"
            pnl_pct = s.get("current_pnl_pct", 0) or 0
            items.append({
                "title": f"{urgency_icon}{signal_icon} {s['ticker']} ({pnl_pct:+.1f}%)",
                "description": s.get("reasoning", "")[:60],
            })

        count = len(sell_signals)
        return {
            "object_type": "list",
            "header_title": f"⚠️ AI 매도 신호 ({count}개)",
            "header_link": {"type": ""},
            "contents": items,
            "buttons": [],
        }

    def _build_portfolio_summary_template(self, summary: dict) -> dict:
        """포트폴리오 요약 FeedTemplate을 생성합니다."""
        total_pnl = summary.get("total_unrealized_pnl", 0)
        total_pnl_pct = summary.get("total_unrealized_pnl_pct", 0)
        pnl_icon = "📈" if total_pnl >= 0 else "📉"
        pnl_sign = "+" if total_pnl >= 0 else ""

        top_holdings = []
        for h in summary.get("holdings", [])[:3]:
            sign = "+" if h["unrealized_pnl_pct"] >= 0 else ""
            top_holdings.append(f"{h['ticker']}: {sign}{h['unrealized_pnl_pct']:.1f}%")
        holdings_str = " | ".join(top_holdings) if top_holdings else "보유 없음"

        return {
            "object_type": "feed",
            "content": {
                "title": f"{pnl_icon} 오늘의 포트폴리오 요약",
                "description": (
                    f"보유: {summary.get('total_holdings', 0)}개 종목\n"
                    f"평가손익: {pnl_sign}${total_pnl:,.0f} ({pnl_sign}{total_pnl_pct:.2f}%)\n"
                    f"상위: {holdings_str}"
                ),
                "link": {"type": ""},
            },
            "buttons": [],
        }

    def _build_price_alert_template(self, alerts: list[dict]) -> dict:
        """가격 알림 ListTemplate을 생성합니다. 최대 5건."""
        icon_map = {
            "STOP_LOSS": "🔴",
            "TARGET_PRICE": "🎯",
            "VOLUME_SURGE": "📊",
        }
        items = []
        for a in alerts[:5]:
            icon = icon_map.get(a.get("alert_type", ""), "⚠️")
            price_str = f"${a['current_price']:.2f}" if a.get("current_price") else "N/A"
            threshold_str = f"${a['threshold']:.2f}" if a.get("threshold") else "N/A"
            items.append({
                "title": f"{icon} {a['ticker']} — {a.get('alert_type', '')}",
                "description": f"현재가 {price_str} / 기준 {threshold_str}",
            })

        count = len(alerts)
        return {
            "object_type": "list",
            "header_title": f"🔔 가격 알림 ({count}건)",
            "header_link": {"type": ""},
            "contents": items,
            "buttons": [],
        }

    def _build_text_template(self, text: str) -> dict:
        """단순 텍스트 메시지 템플릿을 생성합니다."""
        return {
            "object_type": "text",
            "text": text,
            "link": {"type": ""},
            "button_title": "",
        }

    # ── 공개 메서드 ─────────────────────────────────────────────────────────────

    def send_buy_recommendations(self, recommendations: list[dict]) -> bool:
        """
        BUY/STRONG_BUY 추천 목록을 카카오톡으로 전송합니다.
        추천이 없으면 전송하지 않습니다.
        """
        buy_recs = [r for r in recommendations if r.get("action") in ("BUY", "STRONG_BUY")]
        if not buy_recs:
            logger.debug("[카카오] 매수 추천 없음, 알림 스킵")
            return True

        template = self._build_buy_recommendation_template(buy_recs)
        success = self._send_message(template)
        if success:
            logger.info(f"[카카오] 매수 추천 알림 전송 완료 ({len(buy_recs)}개)")
        return success

    def send_sell_signals(self, sell_signals: list[dict]) -> bool:
        """
        SELL/STRONG_SELL 신호 목록을 카카오톡으로 전송합니다.
        신호가 없으면 전송하지 않습니다.
        """
        active_signals = [s for s in sell_signals if s.get("signal") in ("SELL", "STRONG_SELL")]
        if not active_signals:
            logger.debug("[카카오] 매도 신호 없음, 알림 스킵")
            return True

        template = self._build_sell_signal_template(active_signals)
        success = self._send_message(template)
        if success:
            logger.info(f"[카카오] 매도 신호 알림 전송 완료 ({len(active_signals)}개)")
        return success

    def send_daily_summary(self) -> bool:
        """매일 장 마감 후 포트폴리오 요약을 카카오톡으로 전송합니다."""
        from portfolio.portfolio_manager import portfolio_manager
        try:
            summary = portfolio_manager.get_summary()
        except Exception as e:
            logger.error(f"[카카오] 포트폴리오 조회 실패: {e}")
            return False

        template = self._build_portfolio_summary_template(summary)
        success = self._send_message(template)
        if success:
            logger.info("[카카오] 일일 포트폴리오 요약 전송 완료")
        return success

    def send_price_alerts(self, alerts: list[dict]) -> bool:
        """
        가격 알림 목록을 카카오톡으로 전송합니다.
        카카오 미설정 시 로그만 출력(graceful).
        """
        if not alerts:
            logger.debug("[카카오] 가격 알림 없음, 스킵")
            return True

        if not self._is_configured():
            for a in alerts:
                logger.info(f"[가격 알림] {a.get('message', a)}")
            return True

        template = self._build_price_alert_template(alerts)
        success = self._send_message(template)
        if success:
            logger.info(f"[카카오] 가격 알림 전송 완료 ({len(alerts)}건)")
        return success

    def test_connection(self) -> bool:
        """카카오 연결 테스트 메시지를 전송합니다."""
        if not self._is_configured():
            logger.warning("[카카오] KAKAO_ACCESS_TOKEN이 설정되지 않았습니다.")
            logger.info("  .env 파일에 KAKAO_ACCESS_TOKEN을 추가하세요.")
            return False

        template = self._build_text_template(
            "✅ 주식 관리 시스템 카카오톡 연결 테스트 성공!\n"
            "AI 매수/매도 추천 알림이 이 채널로 전송됩니다."
        )
        return self._send_message(template)


# 싱글톤 인스턴스
kakao_notifier = KakaoNotifier()
