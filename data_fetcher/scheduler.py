"""
데이터 수집 스케줄러 모듈
APScheduler를 사용하여 주기적/시각 기반 데이터 수집 작업을 관리합니다.

스케줄 구성:
  ┌─────────────────────────────────────────────────────────┐
  │  작업명                  주기          설명              │
  ├─────────────────────────────────────────────────────────┤
  │  realtime_price          N분마다       현재가 갱신        │
  │  daily_price_update      매일 장마감   일봉 데이터 저장   │
  │  news_fetch              매시간        뉴스 수집          │
  │  stock_info_sync         매주 월요일   종목 메타 동기화   │
  │  technical_calc          매일 장마감   기술 지표 계산     │
  └─────────────────────────────────────────────────────────┘
"""
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from config.settings import settings
from data_fetcher.market_data import market_fetcher


# ─────────────────────────────────────────
# 스케줄 작업 함수 정의
# ─────────────────────────────────────────


def job_realtime_price_update():
    """현재가 갱신 작업 (N분마다 실행)"""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:  # 토요일=5, 일요일=6
        logger.debug("[스케줄] 주말, 실시간 가격 갱신 스킵")
        return {}
    logger.debug(f"[스케줄] 실시간 가격 갱신 시작 ({datetime.now().strftime('%H:%M:%S')})")
    prices = market_fetcher.fetch_all_realtime_prices()
    logger.info(f"[스케줄] 실시간 가격 갱신 완료: {len(prices)}개 종목")
    return prices


def job_daily_price_update():
    """일봉 데이터 저장 (매일 장 마감 후)"""
    logger.info("[스케줄] 일봉 데이터 업데이트 시작")
    result = market_fetcher.update_daily_prices()
    logger.success(f"[스케줄] 일봉 데이터 업데이트 완료: {result}")


def job_news_fetch():
    """뉴스 수집 (매시간)"""
    logger.debug("[스케줄] 뉴스 수집 시작")
    count = market_fetcher.fetch_all_news()
    logger.info(f"[스케줄] 뉴스 수집 완료: {count}건")


def job_stock_info_sync():
    """종목 메타 정보 동기화 (매주 월요일)"""
    logger.info("[스케줄] 종목 정보 동기화 시작")
    result = market_fetcher.sync_all_watchlist()
    logger.success(f"[스케줄] 종목 정보 동기화 완료: {result}")


def job_daily_ai_analysis():
    """AI 매수 추천 분석 (평일 장전 08:30)"""
    logger.info("[스케줄] AI 매수 분석 시작")
    try:
        from analysis.ai_analyzer import ai_analyzer
        results = ai_analyzer.analyze_all_watchlist()
        buy_count = sum(1 for a in results.values() if a in ("BUY", "STRONG_BUY"))
        logger.success(f"[스케줄] AI 매수 분석 완료 — 매수 추천: {buy_count}개")

        # 알림 전송 (카카오 + 텔레그램)
        if buy_count > 0:
            recs = ai_analyzer.get_todays_recommendations()
            buy_recs = [r for r in recs if r["action"] in ("BUY", "STRONG_BUY")]
            try:
                from notifications.kakao import kakao_notifier
                kakao_notifier.send_buy_recommendations(buy_recs)
            except Exception as e:
                logger.debug(f"[스케줄] 카카오 알림 스킵: {e}")
            try:
                from notifications.telegram import telegram_notifier
                telegram_notifier.send_buy_recommendations(buy_recs)
            except Exception as e:
                logger.debug(f"[스케줄] 텔레그램 알림 스킵: {e}")
    except Exception as e:
        logger.error(f"[스케줄] AI 매수 분석 실패: {e}")


def job_sell_analysis():
    """보유 종목 매도 신호 분석 (평일 장 시작 후 09:30)"""
    logger.info("[스케줄] AI 매도 신호 분석 시작")
    try:
        from analysis.sell_analyzer import sell_analyzer
        results = sell_analyzer.analyze_all_holdings()
        sell_count = sum(1 for s in results.values() if s in ("SELL", "STRONG_SELL"))
        logger.success(f"[스케줄] AI 매도 분석 완료 — 매도 신호: {sell_count}개")

        # 알림 전송 (카카오 + 텔레그램)
        if sell_count > 0:
            signals = sell_analyzer.get_active_sell_signals()
            sell_sigs = [s for s in signals if s["signal"] in ("SELL", "STRONG_SELL")]
            try:
                from notifications.kakao import kakao_notifier
                kakao_notifier.send_sell_signals(sell_sigs)
            except Exception as e:
                logger.debug(f"[스케줄] 카카오 알림 스킵: {e}")
            try:
                from notifications.telegram import telegram_notifier
                telegram_notifier.send_sell_signals(sell_sigs)
            except Exception as e:
                logger.debug(f"[스케줄] 텔레그램 알림 스킵: {e}")
    except Exception as e:
        logger.error(f"[스케줄] AI 매도 분석 실패: {e}")


def job_update_backtesting():
    """백테스팅 결과 업데이트 (매일 17:00 ET — 장 마감 후 충분한 시간 경과 후)"""
    logger.info("[스케줄] 백테스팅 결과 업데이트 시작")
    try:
        from analysis.backtester import backtester
        n = backtester.update_outcomes()
        logger.success(f"[스케줄] 백테스팅 업데이트 완료: {n}건")
    except Exception as e:
        logger.error(f"[스케줄] 백테스팅 업데이트 실패: {e}")


def job_price_alert_check():
    """가격 알림 체크 (장중 5분마다 09:30~16:00)"""
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    # 09:30 이전 실행 시 스킵
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        logger.debug("[스케줄] 장 개장 전, 가격 알림 체크 스킵")
        return
    # 16:00 이후 실행 시 스킵
    if now.hour >= 16:
        logger.debug("[스케줄] 장 마감 후, 가격 알림 체크 스킵")
        return
    logger.debug(f"[스케줄] 가격 알림 체크 ({now.strftime('%H:%M')})")
    try:
        from notifications.alert_manager import alert_manager
        alert_manager.check_and_notify()
    except Exception as e:
        logger.error(f"[스케줄] 가격 알림 체크 실패: {e}")


def job_daily_portfolio_summary():
    """일일 포트폴리오 요약 알림 (평일 장 마감 후 16:35)"""
    logger.info("[스케줄] 포트폴리오 요약 알림 시작")
    try:
        from notifications.kakao import kakao_notifier
        kakao_notifier.send_daily_summary()
    except Exception as e:
        logger.debug(f"[스케줄] 카카오 요약 알림 스킵: {e}")
    try:
        from notifications.telegram import telegram_notifier
        telegram_notifier.send_daily_summary()
    except Exception as e:
        logger.debug(f"[스케줄] 텔레그램 요약 알림 스킵: {e}")
    logger.success("[스케줄] 포트폴리오 요약 알림 전송 완료")


# ─────────────────────────────────────────
# 스케줄러 클래스
# ─────────────────────────────────────────

class DataScheduler:
    """
    APScheduler 기반 데이터 수집 스케줄러

    사용 예시:
        scheduler = DataScheduler()
        scheduler.start()
        # ... 프로그램 실행 ...
        scheduler.stop()
    """

    def __init__(self):
        self._scheduler = BackgroundScheduler(
            job_defaults={
                "coalesce": True,        # 밀린 작업 1번만 실행
                "max_instances": 1,      # 같은 작업 중복 실행 방지
                "misfire_grace_time": 60 # 60초 이내 지연은 실행 허용
            },
            timezone="America/New_York"  # 미국 동부시각 기준 (NYSE/NASDAQ)
        )
        self._running = False

    def _register_jobs(self):
        """모든 스케줄 작업을 등록합니다."""

        # 1. 실시간 가격 갱신 (N분마다)
        self._scheduler.add_job(
            job_realtime_price_update,
            trigger=IntervalTrigger(minutes=settings.FETCH_INTERVAL_MINUTES),
            id="realtime_price",
            name=f"실시간 가격 갱신 ({settings.FETCH_INTERVAL_MINUTES}분마다)",
            replace_existing=True,
        )

        # 2. 일봉 데이터 저장 (평일 오후 4시 30분 - NYSE 마감 30분 후)
        self._scheduler.add_job(
            job_daily_price_update,
            trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=30),
            id="daily_price_update",
            name="일봉 데이터 업데이트 (장 마감 후)",
            replace_existing=True,
        )

        # 3. 뉴스 수집 (매시간 정각)
        self._scheduler.add_job(
            job_news_fetch,
            trigger=CronTrigger(minute=0),
            id="news_fetch",
            name="뉴스 수집 (매시간)",
            replace_existing=True,
        )

        # 4. 종목 메타 정보 동기화 (매주 월요일 오전 8시)
        self._scheduler.add_job(
            job_stock_info_sync,
            trigger=CronTrigger(day_of_week="mon", hour=8, minute=0),
            id="stock_info_sync",
            name="종목 정보 동기화 (매주 월요일)",
            replace_existing=True,
        )

        # 5. AI 매수 추천 분석 (평일 오전 8시 30분 — 장 개장 전)
        self._scheduler.add_job(
            job_daily_ai_analysis,
            trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
            id="daily_ai_analysis",
            name="AI 매수 추천 분석 (장전)",
            replace_existing=True,
        )

        # 6. AI 매도 신호 분석 (평일 오전 9시 30분 — 장 개장 후)
        self._scheduler.add_job(
            job_sell_analysis,
            trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=30),
            id="sell_analysis",
            name="AI 매도 신호 분석 (장 개장 후)",
            replace_existing=True,
        )

        # 7. 포트폴리오 요약 카카오 알림 (평일 오후 4시 35분 — 장 마감 후)
        self._scheduler.add_job(
            job_daily_portfolio_summary,
            trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=35),
            id="daily_portfolio_summary",
            name="포트폴리오 요약 알림 (장 마감 후)",
            replace_existing=True,
        )

        # 8. 백테스팅 결과 업데이트 (매일 17:00 ET)
        self._scheduler.add_job(
            job_update_backtesting,
            trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=0),
            id="update_backtesting",
            name="백테스팅 결과 업데이트 (장 마감 후)",
            replace_existing=True,
        )

        # 9. 가격 알림 체크 (장중 5분마다 09:00~15:59)
        self._scheduler.add_job(
            job_price_alert_check,
            trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5"),
            id="price_alert_check",
            name="가격 알림 체크 (장중 5분마다)",
            replace_existing=True,
        )

        logger.info("스케줄 작업 등록 완료:")
        for job in self._scheduler.get_jobs():
            logger.info(f"  - [{job.id}] {job.name}")

    def start(self):
        """스케줄러를 시작합니다."""
        if self._running:
            logger.warning("스케줄러가 이미 실행 중입니다.")
            return

        self._register_jobs()
        self._scheduler.start()
        self._running = True
        logger.success("데이터 수집 스케줄러 시작됨")

    def stop(self):
        """스케줄러를 안전하게 종료합니다."""
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("데이터 수집 스케줄러 종료됨")

    def run_now(self, job_id: str) -> bool:
        """
        특정 작업을 즉시 실행합니다 (테스트/수동 실행용).

        Args:
            job_id: 'realtime_price' | 'daily_price_update' | 'news_fetch' | 'stock_info_sync'
        """
        job_map = {
            "realtime_price": job_realtime_price_update,
            "daily_price_update": job_daily_price_update,
            "news_fetch": job_news_fetch,
            "stock_info_sync": job_stock_info_sync,
            "daily_ai_analysis": job_daily_ai_analysis,
            "sell_analysis": job_sell_analysis,
            "daily_portfolio_summary": job_daily_portfolio_summary,
            "update_backtesting": job_update_backtesting,
            "price_alert_check": job_price_alert_check,
        }
        fn = job_map.get(job_id)
        if fn is None:
            logger.error(f"알 수 없는 job_id: {job_id}")
            return False

        logger.info(f"[수동 실행] {job_id}")
        fn()
        return True

    def get_status(self) -> list[dict]:
        """
        등록된 작업의 현재 상태를 반환합니다.
        """
        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else "N/A",
            })
        return jobs

    @property
    def is_running(self) -> bool:
        return self._running


# 싱글톤 인스턴스
data_scheduler = DataScheduler()
