"""
주식 관리 자동화 시스템 - 메인 진입점

실행 모드:
  python main.py init         - DB 초기화 + 과거 데이터 로드
  python main.py run          - 실시간 스케줄러 시작 (데몬 모드)
  python main.py status       - 포트폴리오 현황 출력
  python main.py fetch        - 즉시 데이터 수집 (수동 트리거)
  python main.py calc         - 기술적 지표 즉시 계산
  python main.py analyze      - AI 매수 추천 즉시 실행
  python main.py sell_check   - AI 매도 신호 즉시 분석
  python main.py notify_test  - 카카오톡 연결 테스트
"""
import signal
import sys
import threading
import time

from loguru import logger

from config.settings import settings
from database.connection import check_connection, init_db
from data_fetcher.market_data import market_fetcher
from data_fetcher.scheduler import data_scheduler
from analysis.technical_analysis import technical_analyzer
from portfolio.portfolio_manager import portfolio_manager


def setup_logging():
    """로그 설정: 콘솔 + 파일 동시 출력"""
    logger.remove()  # 기본 핸들러 제거
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True,
    )
    logger.add(
        settings.LOG_FILE,
        level="DEBUG",
        rotation="10 MB",    # 10MB 초과 시 새 파일
        retention="30 days", # 30일 후 삭제
        compression="zip",
        encoding="utf-8",
    )


def cmd_init(years: int = 2):
    """
    [init] DB 초기화 및 과거 데이터 초기 로드
    최초 실행 시 1회만 수행합니다.
    """
    logger.info("=" * 50)
    logger.info("주식 관리 시스템 초기화 시작")
    logger.info(f"  관심 종목: {settings.WATCHLIST_TICKERS}")
    logger.info(f"  DB URL   : {settings.DATABASE_URL}")
    logger.info("=" * 50)

    # DB 연결 확인
    if not check_connection():
        logger.error("DB 연결 실패. 종료합니다.")
        sys.exit(1)

    # 테이블 생성
    init_db()

    # 과거 데이터 로드
    market_fetcher.initial_load(years=years)

    # 기술적 지표 계산
    logger.info("기술적 지표 초기 계산 중...")
    technical_analyzer.calculate_all()

    logger.success("초기화 완료! 이제 'python main.py run' 으로 실시간 모드를 시작하세요.")


shutdown_event = threading.Event()


def handle_signal(signum, frame):
    """SIGTERM/SIGINT 시그널 핸들러 (Docker graceful shutdown 지원)"""
    logger.info(f"종료 신호 수신 (signal {signum})")
    shutdown_event.set()


def cmd_run():
    """
    [run] 실시간 스케줄러 시작 (Ctrl+C로 종료)
    """
    logger.info("실시간 데이터 수집 스케줄러 시작")
    logger.info(f"  가격 갱신 주기: {settings.FETCH_INTERVAL_MINUTES}분마다")

    # DB 연결 확인
    if not check_connection():
        logger.error("DB 연결 실패. 종료합니다.")
        sys.exit(1)

    # 시그널 핸들러 등록 (Docker SIGTERM 대응)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # 스케줄러 시작
    data_scheduler.start()

    logger.info("스케줄러 실행 중... (종료: Ctrl+C 또는 SIGTERM)")
    try:
        shutdown_event.wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("종료 신호 수신")
    finally:
        data_scheduler.stop()
        logger.info("시스템 종료 완료")


def cmd_status():
    """[status] 현재 포트폴리오 현황 출력"""
    portfolio_manager.print_summary()


def cmd_fetch():
    """[fetch] 즉시 전체 데이터 수집"""
    logger.info("수동 데이터 수집 시작...")
    market_fetcher.sync_all_watchlist()
    market_fetcher.update_daily_prices()
    market_fetcher.fetch_all_news()
    logger.success("수동 데이터 수집 완료")


def cmd_calc():
    """[calc] 기술적 지표 즉시 계산"""
    logger.info("기술적 지표 계산 시작...")
    results = technical_analyzer.calculate_all()
    for ticker, count in results.items():
        logger.info(f"  [{ticker}] {count}개 신규 지표 저장")
    logger.success("기술적 지표 계산 완료")


def cmd_analyze():
    """[analyze] AI 매수 추천 즉시 실행"""
    from analysis.ai_analyzer import ai_analyzer
    logger.info("AI 매수 분석 시작...")
    results = ai_analyzer.analyze_all_watchlist()
    logger.info("─" * 40)
    for ticker, action in results.items():
        logger.info(f"  [{ticker}] → {action}")
    logger.success("AI 매수 분석 완료")


def cmd_sell_check():
    """[sell_check] 보유 종목 AI 매도 신호 분석"""
    from analysis.sell_analyzer import sell_analyzer
    logger.info("AI 매도 신호 분석 시작...")
    results = sell_analyzer.analyze_all_holdings()
    if not results:
        logger.info("보유 종목이 없습니다.")
        return
    logger.info("─" * 40)
    for ticker, signal in results.items():
        logger.info(f"  [{ticker}] → {signal}")
    logger.success("AI 매도 신호 분석 완료")


def cmd_notify_test():
    """[notify_test] 카카오톡 + 텔레그램 연결 테스트"""
    from notifications.kakao import kakao_notifier
    from notifications.telegram import telegram_notifier

    logger.info("카카오톡 연결 테스트...")
    if kakao_notifier.test_connection():
        logger.success("카카오톡 연결 테스트 성공!")
    else:
        logger.warning("카카오톡 연결 테스트 실패 (KAKAO_ACCESS_TOKEN 확인)")

    logger.info("텔레그램 연결 테스트...")
    if telegram_notifier.test_connection():
        logger.success("텔레그램 연결 테스트 성공!")
    else:
        logger.warning("텔레그램 연결 테스트 실패 (TELEGRAM_BOT_TOKEN/CHAT_ID 확인)")


def main():
    setup_logging()

    commands = {
        "init": cmd_init,
        "run": cmd_run,
        "status": cmd_status,
        "fetch": cmd_fetch,
        "calc": cmd_calc,
        "analyze": cmd_analyze,
        "sell_check": cmd_sell_check,
        "notify_test": cmd_notify_test,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(__doc__)
        print(f"사용 가능한 명령어: {', '.join(commands.keys())}")
        sys.exit(1)

    cmd = sys.argv[1]
    logger.info(f"명령어 실행: {cmd}")
    commands[cmd]()


if __name__ == "__main__":
    main()
