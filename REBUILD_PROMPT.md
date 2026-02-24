# 주식 관리 자동화 시스템 — 완전 재구축 프롬프트

## 프로젝트 개요

미국 주식 포트폴리오 자동 관리 시스템을 처음부터 구축해주세요.
yfinance로 시장 데이터를 수집하고, 기술적 지표를 계산하고, Google Gemini AI로 매수/매도 분석을 수행하고, 카카오톡/텔레그램으로 알림을 보내고, Streamlit 대시보드로 시각화하는 풀스택 시스템입니다.

**파이프라인:** yfinance → SQLite DB → 기술적 분석 → Gemini AI 분석 → 알림(카카오/텔레그램) → Streamlit 대시보드

**배포 환경:** Synology NAS, Docker Compose (scheduler + dashboard 2개 서비스)

---

## 기술 스택

- **Python 3.11+**
- **데이터 수집:** yfinance, vaderSentiment (뉴스 감성)
- **DB:** SQLite (WAL mode), SQLAlchemy 2.0 ORM (mapped_column)
- **AI:** google-genai SDK (NOT deprecated google-generativeai), Gemini 2.5 Flash
- **스케줄링:** APScheduler 3.x (BackgroundScheduler)
- **대시보드:** Streamlit + Plotly
- **알림:** requests (카카오), httpx (텔레그램)
- **기술 지표:** ta 라이브러리
- **로깅:** loguru

---

## 디렉토리 구조

```
stock-manage/
├── main.py                          # CLI 엔트리포인트
├── config/
│   ├── settings.py                  # 환경변수 기반 설정 (싱글톤)
│   └── tickers.py                   # 티커 유니버스 (~818개)
├── database/
│   ├── connection.py                # SQLite 연결 + 컨텍스트 매니저
│   └── models.py                    # SQLAlchemy ORM 모델 10개
├── data_fetcher/
│   ├── market_data.py               # yfinance 데이터 수집
│   └── scheduler.py                 # APScheduler 10개 잡
├── analysis/
│   ├── technical_analysis.py        # 기술적 지표 계산
│   ├── ai_analyzer.py               # Gemini 매수 분석
│   ├── sell_analyzer.py             # Gemini 매도 분석
│   ├── risk_manager.py              # 포지션/섹터 리스크 관리
│   └── backtester.py                # AI 추천 사후검증
├── portfolio/
│   └── portfolio_manager.py         # 매수/매도/보유 관리
├── notifications/
│   ├── kakao.py                     # 카카오톡 나에게 보내기
│   ├── telegram.py                  # 텔레그램 봇
│   └── alert_manager.py             # 가격 알림 엔진
├── dashboard/
│   ├── app.py                       # Streamlit 메인
│   ├── style.py                     # CSS 주입
│   ├── utils.py                     # 공통 유틸리티
│   └── pages/
│       ├── portfolio.py
│       ├── chart.py
│       ├── ai_buy.py
│       ├── ai_sell.py
│       └── news.py
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env
```

---

## 핵심 패턴 (모든 모듈에 일관 적용)

1. **DB 접근:** `with get_db() as db:` 컨텍스트 매니저 (자동 commit/rollback)
2. **싱글톤:** 각 모듈 하단에 `instance = ClassName()` (DI 없음)
3. **로깅:** `from loguru import logger`
4. **설정:** `from config.settings import settings`
5. **AI SDK:** `google.genai.Client` (새 SDK), NOT `google.generativeai`
6. **Thinking 모델:** `types.ThinkingConfig(thinking_budget=1024)`로 비용 제한
7. **캐시:** Streamlit `@st.cache_data(ttl=초)` + 액션 후 `st.cache_data.clear()`

---

## 1. config/settings.py (~114줄)

`Settings` 클래스, `.env` 파일에서 `os.getenv()` 로드.

**모든 설정 필드:**
```
# AI
GEMINI_API_KEY, GEMINI_MODEL="gemini-2.5-flash", AI_MAX_TOKENS=65536,
AI_TEMPERATURE=0.40, BUY_CONFIDENCE_THRESHOLD=0.50, SELL_CONFIDENCE_THRESHOLD=0.50,
GEMINI_CALL_DELAY=0.5, GEMINI_BACKOFF_BASE=2.0, GEMINI_TIMEOUT=300, GEMINI_CONCURRENCY=5

# 알림
KAKAO_REST_API_KEY, KAKAO_ACCESS_TOKEN, KAKAO_REFRESH_TOKEN
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# DB & 대시보드
DATABASE_URL="sqlite:///{BASE_DIR}/stock_manage.db"
DASHBOARD_PASSWORD="" (빈값이면 인증 없음)

# 스케줄러
FETCH_INTERVAL_MINUTES=10, DAILY_ANALYSIS_TIME="09:00"

# 로깅
LOG_LEVEL="INFO", LOG_FILE="{BASE_DIR}/logs/stock_manage.log"

# 기술적 분석 상수 (하드코딩)
RSI_OVERSOLD=30, RSI_OVERBOUGHT=70, BOLLINGER_PERIOD=20, BOLLINGER_STD=2.0,
MA_SHORT=20, MA_LONG=50, MA_SIGNAL=9
```

**WATCHLIST_TICKERS 프로퍼티:**
우선순위: DB 보유종목 → 환경변수 → ALL_TICKERS 폴백

---

## 2. config/tickers.py (~624줄)

**티커 유니버스 구성:**
- `NASDAQ_100`: ~101개
- `SP500`: ~503개 (섹터별 분류)
- `POPULAR_ETFS`: ~143개 (SPY, QQQ, 섹터/레버리지/국제/채권/테마 ETF)
- `MID_CAP`: ~100개
- `SMALL_CAP_GROWTH`: ~50개
- `ALL_TICKERS = sorted(set(전체))` → ~818개

**`TICKER_INDEX: dict[str, list[str]]`** — 각 티커가 어떤 카테고리에 속하는지 매핑
**`get_tickers_by_index(index_name)`** — 카테고리별 티커 필터링

---

## 3. database/models.py (~405줄)

SQLAlchemy 2.0 `mapped_column` 스타일. **ORM 모델 10개:**

### Stock
ticker(unique, indexed), name, sector, industry, market_cap, currency, exchange, country,
short_ratio, short_pct_of_float, float_shares, is_active, created_at, updated_at

### PriceHistory
stock_id(FK), timestamp(indexed), interval(default "1d"), OHLCV, adj_close
UniqueConstraint(stock_id, timestamp, interval)

### TechnicalIndicator
stock_id(FK), date(indexed),
rsi_14, macd, macd_signal, macd_hist,
bb_upper, bb_middle, bb_lower,
ma_20, ma_50, ma_200, volume_ma_20,
adx_14, atr_14, obv, stoch_rsi_k, stoch_rsi_d
UniqueConstraint(stock_id, date)

### PortfolioHolding
stock_id(FK, unique), quantity, avg_buy_price, total_invested,
current_price, unrealized_pnl, unrealized_pnl_pct, first_bought_at, last_updated_at

### Transaction
stock_id(FK), action('BUY'/'SELL'), quantity, price, total_amount, fee(default 0),
realized_pnl, note(Text), executed_at(indexed)

### AIRecommendation
stock_id(FK), recommendation_date(indexed),
action('STRONG_BUY'/'BUY'/'HOLD'), confidence, target_price, stop_loss, reasoning(Text),
technical_score, fundamental_score, sentiment_score,
price_at_recommendation, is_executed(default False), outcome_price, outcome_return

### SellSignal
stock_id(FK), signal_date(indexed),
signal('STRONG_SELL'/'SELL'/'HOLD'), urgency('HIGH'/'NORMAL'/'LOW', default 'NORMAL'),
confidence, reasoning(Text), suggested_sell_price,
technical_score, position_risk_score, fundamental_score, sell_pressure,
exit_strategy(String(20)), current_price, current_pnl_pct, is_acted_upon(default False)

### PriceAlert
stock_id(FK), alert_type(String(20)), threshold_value, is_active(default True), last_triggered_at
Index(stock_id, alert_type)

### AlertHistory
stock_id(FK), alert_type, trigger_price, triggered_at, message(Text), is_sent(default False)
Index(stock_id, alert_type, triggered_at)

### MarketNews
ticker(nullable, indexed), title, summary(Text), url(unique), source, sentiment(Float -1~+1),
published_at(indexed), fetched_at

---

## 4. database/connection.py (~143줄)

- SQLite 전용 `check_same_thread=False`, `pool_size=5`, `max_overflow=10`
- **PRAGMA 설정:** `journal_mode=WAL`, `foreign_keys=ON`, `wal_autocheckpoint=1000`, `synchronous=NORMAL`, `busy_timeout=5000`
- `SessionLocal`: `autocommit=False, autoflush=False, expire_on_commit=False`
- `init_db()`: `Base.metadata.create_all(checkfirst=True)` + 자동 컬럼 마이그레이션
- `get_db()`: yield → commit / except → rollback / finally → close
- `_migrate_add_columns()`: `PRAGMA table_info()`로 기존 컬럼 감지 후 누락 컬럼 ALTER TABLE ADD

---

## 5. data_fetcher/market_data.py (~610줄)

`MarketDataFetcher` 클래스. 상수: `BATCH_SIZE=100`, `BATCH_DELAY_SEC=1.5`, `NEWS_TARGET_LIMIT=100`

### 주요 메서드:
- `_get_ticker(symbol)`: OrderedDict LRU 캐시 (MAX_CACHE_SIZE=200)
- `sync_stock_info(ticker, db)`: yfinance fast_info/info → Stock upsert (price>0 검증)
- `sync_all_watchlist()`: 배치 처리, {ticker: bool}
- `fetch_price_history(ticker, period, interval)`: yfinance.history → UTC naive 변환
- `save_price_history(ticker, period, interval)`: 행 검증 (close>0, volume>=0, high>=low) → upsert
- `fetch_realtime_price(ticker)`: fast_info → fallback 5d history
- `update_daily_prices()`: 전체 워치리스트 5d 가격 저장
- `fetch_and_save_news(ticker, db)`: yfinance .news → VADER 감성 분석 → URL 중복제거 → 저장
- `_get_news_target_tickers()`: 보유종목 + 최근 7일 BUY 추천 + 워치리스트 → 최대 100개
- `initial_load(years=2)`: sync → 2년 히스토리 → 뉴스

---

## 6. data_fetcher/scheduler.py (~441줄)

`DataScheduler` 클래스. BackgroundScheduler(coalesce=True, max_instances=1, misfire_grace_time=60, timezone="America/New_York")

### NYSE 휴일 감지:
- 주말 체크 (Mon-Fri만)
- 고정 휴일: 1/1, 6/19, 7/4, 12/25
- 변동 휴일: MLK Day(1월 3째 월), Presidents Day(2월 3째 월), Memorial Day(5월 마지막 월),
  Labor Day(9월 1째 월), Thanksgiving(11월 4째 목)

### 10개 스케줄 잡:

| # | 잡 | 트리거 | 시간(ET) | 액션 |
|---|---|-------|---------|------|
| 1 | realtime_price_update | Interval(분) | 매 N분 (거래일만) | fetch_all_realtime_prices → PortfolioHolding.current_price 갱신 |
| 2 | daily_price_update | Cron | 월-금 16:30 | update_daily_prices() |
| 3 | news_fetch | Cron | 월-금 매시 정각 | fetch_all_news() |
| 4 | stock_info_sync | Cron | 월요일 08:00 | sync_all_watchlist() |
| 5 | daily_ai_analysis | Cron | 월-금 09:30 | analyze_all_watchlist() → 카카오/텔레그램 매수 알림 |
| 6 | sell_analysis | Cron | 월-금 10:00 | analyze_all_holdings() → 카카오/텔레그램 매도 알림 |
| 7 | daily_portfolio_summary | Cron | 월-금 16:35 | 카카오/텔레그램 일일 요약 |
| 8 | update_backtesting | Cron | 월-금 17:00 | backtester.update_outcomes() |
| 9 | price_alert_check | Interval(5분) | 9시-15시 거래일 | alert_manager.check_and_notify() |
| 10 | technical_calc | Cron | 월-금 16:45 | technical_analyzer.calculate_all() |

---

## 7. analysis/technical_analysis.py (~266줄)

`TechnicalAnalyzer` 클래스. ta 라이브러리 사용.

- `calculate_and_save(ticker)`: 최소 30일 데이터 필요
  - RSI(14), MACD(26,12,9), BB(20,2), ADX(14), ATR(14), MA20/50/200, Volume_MA20, OBV, StochRSI(14,3,3)
  - 기존 날짜 pre-load로 N+1 방지, upsert
- `calculate_all()`: 전체 워치리스트, 50개마다 진행률 로그
- `get_latest_indicators(ticker)`: 최신 지표 dict 반환

---

## 8. analysis/ai_analyzer.py (~1477줄) ⭐ 핵심 모듈

`AIAnalyzer` 클래스. **이것이 시스템의 핵심입니다.**

### 8.1 Gemini 시스템 프롬프트 (~95줄)
6단계 분석 프레임워크:
1. 기술적 분석 (RSI, MACD, BB, MA 정렬, ADX, ATR, 거래량, StochRSI)
2. 펀더멘탈 (PE, P/B, P/S, 배당, EPS, 매출성장, 마진, D/E, ROE, FCF)
3. 시장 심리 (뉴스 감성, VIX, SPY/QQQ 동향)
4. 리스크 평가 (손절가, 목표가, R/R 비율)
5. 종합 판단 (STRONG_BUY/BUY/HOLD)
6. JSON 응답 형식 지정

### 8.2 분석 컨텍스트 빌드 (`_build_analysis_context`)
수집 데이터:
- 가격: 최근 35일 OHLCV
- 지표: 최근 2일 (MACD 크로스오버 감지용)
- 뉴스: 최근 7개 (30일 내)
- 종목 정보: Stock 모델 필드
- 펀더멘탈: yfinance.Ticker.info → trailingPE, forwardPE, priceToBook, priceToSalesTrailing12Months, dividendYield, trailingEps, revenueGrowth, profitMargins, debtToEquity, returnOnEquity, freeCashflow, institutionPercentHeld, insiderPercentHeld
- 과거 성과: backtester.get_accuracy_stats(90)
- 시장 컨텍스트: SPY, QQQ, ^VIX, ^TNX 실시간
- 실적 경고: yfinance.calendar["Earnings Date"] 14일 이내

### 8.3 프롬프트 빌드 (`_build_prompt`)
섹션별 서술형:
- Price Action: 5d/10d/20d 수익률, 35일 고저, 거래량 추세, 최근 3 캔들
- Technical: RSI 라벨, MACD+크로스오버, BB 위치%, MA 정렬, ADX 라벨, ATR 일일변동%, 거래량비율, OBV, StochRSI
- Fundamentals: PE/P/B/P/S/배당/EPS/매출성장/마진/D/E/ROE/FCF 한 줄
- Ownership: 공매도비율, 공매도잔고%, 기관보유%, 내부자보유%
- Market Context: SPY/QQQ 변동%, VIX+레짐, 10년 국채
- Earnings Alert (14일 이내 시)
- AI Track Record (백테스트 통계)
- 뉴스 목록 + 감성 이모지

### 8.4 응답 파싱 (`_parse_response`)
- JSON 추출: 직접 파싱 → regex `r'\{[\s\S]*\}' ` 폴백
- 검증: action(STRONG_BUY/BUY/HOLD), confidence(0-1 clamp), reasoning 필수
- weighted_score: 1.5 이상 차이 시 재계산값으로 보정
- target_price: current×1.01 ~ current×1.25 범위 강제
- stop_loss: current×0.88 ~ current×0.99 범위 강제
- 점수(technical/fundamental/sentiment): 0-10 clamp

### 8.5 단일 종목 분석 (`analyze_ticker`)
- 3회 재시도 + 지수 백오프
- ThinkingConfig(thinking_budget=1024), response_mime_type="application/json"
- 신뢰도 미달 시 HOLD로 다운그레이드
- risk_manager.check_can_buy() 경고 (차단은 안 함)
- AIRecommendation DB 저장

### 8.6 우선순위 필터 (`get_priority_tickers`) ⭐⭐ 핵심 알고리즘

**ETF 제외 후 5-Factor 스코어링:**

**VIX 기반 매크로 레짐:**
- high_volatility (VIX>28): 모멘텀 가중=0.25, 리버전 가중=0.75
- transitional (VIX>20): 모멘텀=0.45, 리버전=0.55
- trending (VIX≤20): 모멘텀=0.70, 리버전=0.30

**5-Factor 모델 v2.0:**

**F1 Trend Quality (가중=0.25):**
- T1: 가격>MA20/50/200 각각 +1점 (최대 +3)
- T2: MA20>MA50>MA200 정렬 (+2)
- T3: MA50>MA200 (+1.5)
- T4: MA200 기울기 양수 (+1.5)
- T5: BB position>70% (+1)

**F2 Momentum (가중=레짐 의존):**
- Mo1: MACD 골든크로스 +3, 양수 +1.5~2
- Mo2: RSI 존 (55-65:+2.5, 50-55:+2, 45-50:+1, 65-70:+1.5)
- Mo3: ROC 5일 (>5%:+2.5, >3%:+2, >1%:+1, >0:+0.5)
- Mo4: Bull Trap Guard (거래량<0.8×MA20: ×0.7, MA20/50 아래: ×0.6)

**F3 Mean-Reversion (가중=레짐 의존):**
- Re1: RSI 과매도 (<25:+3.5, <30:+3, <35:+2, <40:+1)
- Re2: StochRSI 과매도 크로스 (+1+1.5)
- Re3: BB position <10%:+2.5, <20%:+2, <30%:+1
- Re4: BB squeeze (+1.5/+0.5)

**F4 Volume (기준 5.0):**
- 거래량비율: >2.5→10, >2→9, >1.5→8, >1.2→7, 0.8-1.2→5, 0.5-0.8→4, <0.5→3
- OBV 강세 다이버전스 +1.5, 확인 +0.5, 약세 -1.5

**F5 ADX Strength:**
- >40→10, >35→9, >30→8, >25→7, >20→5, >15→3.5, ≤15→2

**글로벌 패널티:**
- P1 Falling Knife: 4연속 하락일 ×0.6, 3연속 ×0.75
- P2 MA200 하회: 모멘텀×0.5, 리버전×0.7
- P3 RSI>75: 모멘텀×0.5, 리버전×0.2

**ADX 마이크로 레짐:**
- ADX>30: 모멘텀 +0.05, 리버전 -0.05
- ADX<20: 리버전 +0.10, 모멘텀 -0.10

**섹터 다양성:** 카테고리당 max(3, max_count//5) 캡

### 8.7 전체 분석 (`analyze_all_watchlist`)
- 매 실행 시 오늘의 기존 AIRecommendation **삭제 후 전체 재분석**
- ThreadPoolExecutor(max_workers=GEMINI_CONCURRENCY=5)
- 스태거 딜레이: (idx % concurrency) × 1.0초
- 최대 3회 재시도, ResourceExhausted → 지수 백오프

### 8.8 Top Picks (`get_top_picks`)
BUY/STRONG_BUY 중 composite_score 상위:
```
composite_score = weighted_score×0.40 + confidence×10×0.25 + rr_ratio×0.20 + sentiment_score×0.15
STRONG_BUY 보너스: +0.5, BUY 보너스: +0.25
rr_ratio = (target-price) / (price-stop_loss), 최대 5.0
```

### 8.9 추천 이력/오늘의 추천
- `get_todays_recommendations()`: 오늘 최신 추천, STRONG_BUY → BUY → weighted_score desc
- `get_recommendation_history(days)`: N일 이력

---

## 9. analysis/sell_analyzer.py (~845줄)

`SellAnalyzer` 클래스. 3-Pillar 매도 분석.

### 시스템 프롬프트 (~76줄)
3축 평가:
- 기술적 악화 (0-10)
- 포지션 리스크 (0-10)
- 펀더멘탈/심리 (0-10)
- sell_pressure = 기술×0.45 + 포지션리스크×0.35 + 펀더멘탈×0.20

### 매도 컨텍스트 빌드
- 최근 20일 가격 (ATR 계산용)
- ATR: DB 또는 ta 라이브러리 재계산
- AI stop_loss: 최근 BUY AIRecommendation의 stop_loss
- 뉴스 7개, 펀더멘탈, 보유일수
- high_watermark: 매수 이후 최고가
- drawdown_from_high_pct
- 시장 컨텍스트: SPY, QQQ, VIX

### 프롬프트 빌드
- Trailing Stop: dynamic_threshold = max(3×ATR/현재가, 5%) clamp 20%
  - CRITICAL: 고점 대비 하락이 threshold 이상
  - WARNING: threshold의 70% 이상
- P&L 기반 이익실현:
  - 단기(<30일): +15%에서 경고
  - 중기(30-180일): +25%에서 경고
  - 장기(>180일): +40%에서 경고
- 세금 참고: 300-365일 보유 + 수익 >10%

### 전체 분석
- `analyze_all_holdings()`: ThreadPoolExecutor, 3회 재시도
- `get_active_sell_signals()`: 오늘 최신, STRONG_SELL → SELL → HOLD, 긴급도순

---

## 10. analysis/risk_manager.py (~123줄)

`RiskManager` 클래스.

**제한 상수 (환경변수):**
- MAX_POSITION_PCT=0.10 (10%)
- MAX_HOLDINGS=30
- MAX_SECTOR_PCT=0.40 (40%)
- MAX_PORTFOLIO_LOSS_PCT=-0.15 (-15%)

**`check_can_buy(ticker, sector)`** — 5단계 체크:
1. 총 보유 >= MAX_HOLDINGS → 차단
2. 이미 보유 → 경고만 (허용)
3. 같은 섹터 종목 >= max(3, MAX_HOLDINGS//3) → 차단
4. 섹터 가치 비중 >= MAX_SECTOR_PCT → 차단
5. 포트폴리오 수익률 <= MAX_PORTFOLIO_LOSS_PCT → 차단

---

## 11. analysis/backtester.py (~400줄)

`Backtester` 클래스. TRADING_COST=0.003 (0.3% = 수수료 0.1% + 슬리피지 0.2%)

- `update_outcomes()`: 30일 고정 윈도우, outcome_return = (종가-추천가)/추천가×100 - 거래비용×100
- `get_accuracy_stats(days)`: BUY/STRONG_BUY만, 승률/평균수익/샤프/SPY 알파
- `get_action_breakdown(days)`: 액션별 GroupStats
- `get_monthly_performance(months)`: 월별 통계
- `get_top_performers(n)`: outcome_return 상위 N개
- `_calc_spy_alpha()`: SPY 동기간 수익 대비 초과수익

---

## 12. portfolio/portfolio_manager.py (~460줄)

`PortfolioManager` 클래스.

- `buy(ticker, quantity, price, fee, note, executed_at)`: 가중평균 매수가 계산, Transaction+PortfolioHolding upsert
- `sell(ticker, quantity, price, fee, note, executed_at)`: realized_pnl = (매도가-평균매수가)×수량-수수료, 잔량 0이면 holding 삭제
- `get_holdings(update_prices=True)`: 실시간 가격 갱신, unrealized_pnl 계산, 수익률 내림차순
- `get_summary()`: 총합 통계 + holdings
- `get_transaction_history(days)`: 거래 이력
- `get_realized_pnl_by_period()`: 월별 실현손익
- `get_sector_allocation()`: 섹터별 비중
- `delete_holding(ticker)`: PriceAlert 삭제 → PortfolioHolding 삭제 (거래이력 보존)

---

## 13. notifications/kakao.py (~302줄)

`KakaoNotifier` 클래스. 카카오 "나에게 보내기" API.

- `_refresh_access_token()`: refresh_token으로 access_token 갱신
- `_send_message(template, retry=True)`: 401 시 토큰 갱신 후 재시도
- 템플릿: list (매수추천 최대 5개), list (매도신호), feed (포트폴리오 요약), list (가격알림), text (테스트)
- `send_buy_recommendations()`, `send_sell_signals()`, `send_daily_summary()`, `send_price_alerts()`, `test_connection()`

---

## 14. notifications/telegram.py (~155줄)

`TelegramNotifier` 클래스. httpx 사용.

- `_send_message(text, parse_mode="Markdown")`: 3회 재시도, 429 rate limit 대응 (retry_after 대기)
- `send_buy_recommendations()`, `send_sell_signals()`, `send_daily_summary()`, `send_price_alerts()`, `test_connection()`
- Markdown 포맷, disable_web_page_preview=True

---

## 15. notifications/alert_manager.py (~503줄)

`AlertManager` 클래스.

**쿨다운:** STOP_LOSS=15분, TRAILING_STOP=15분, TARGET_PRICE=60분, VOLUME_SURGE=360분
**유효 알림 유형:** STOP_LOSS, TARGET_PRICE, VOLUME_SURGE, TRAILING_STOP

### check_portfolio_alerts():
- STOP_LOSS: 현재가 <= 임계값 (PriceAlert 또는 AIRec.stop_loss 폴백)
- TARGET_PRICE: 현재가 >= 임계값 (PriceAlert 또는 AIRec.target_price 폴백)
- TRAILING_STOP: dynamic_threshold = max(3×ATR/현재가, 0.05) clamp 0.20
  - (high_watermark - 현재가) / high_watermark >= threshold 시 발화

### check_volume_surge(threshold=3.0):
- 최근 거래량 >= volume_ma_20 × threshold

### check_and_notify():
- portfolio_alerts + volume_surge → 카카오 + 텔레그램 발송

### set_alert(ticker, alert_type, threshold_value):
- 유형 검증 → Stock 조회 → PriceAlert upsert

---

## 16. main.py (~248줄)

CLI 엔트리포인트. sys.argv[1] 디스패치:

| 명령어 | 함수 | 설명 |
|--------|------|------|
| init | cmd_init(years=2) | DB 초기화 + 2년 히스토리 로드 |
| run | cmd_run() | 스케줄러 시작 (SIGTERM 그레이스풀 셧다운) |
| analyze | cmd_analyze() | 매수 분석 + Top 3 출력 + 매도 분석 |
| sell_check | cmd_sell_check() | 매도 분석만 |
| fetch | cmd_fetch() | 가격 + 뉴스 수집 |
| calc | cmd_calc() | 기술 지표 재계산 |
| status | cmd_status() | 포트폴리오 요약 출력 |
| notify_test | cmd_notify_test() | 카카오/텔레그램 연결 테스트 |

---

## 17. Streamlit 대시보드

### dashboard/app.py (~130줄)
- `st.set_page_config(layout="wide")` 첫 호출
- 로그: 파일만 (stderr 제거)
- 비밀번호 인증 (session_state)
- 사이드바 라디오 5개 메뉴: 포트폴리오/차트/AI매수/AI매도/뉴스
- 종목 수 요약 표시

### dashboard/utils.py (~99줄)
- safe_call, safe_div, fmt_dollar, fmt_pct, fmt_score, fmt_count
- 캐시 TTL 상수: REALTIME=30, SHORT=120, MEDIUM=300, LONG=1800, STATIC=3600
- clear_analysis_cache, clear_portfolio_cache
- action_badge_html, urgency_icon, signal_icon, exit_strategy_label

### dashboard/style.py (~220줄)
- 자동 멀티페이지 네비게이션 숨김: `[data-testid="stSidebarNav"] { display: none }`
- 다크 테마: 사이드바 #0e1117, 메트릭 카드 #161b22, 호버 #58a6ff
- 뱃지: badge-buy(초록), badge-sell(빨강), badge-hold(회색), badge-strong-buy
- 긴급도: urgency-high(빨강), urgency-normal(주황), urgency-low(노랑)
- 모바일 반응형 @media 768px

### dashboard/pages/ai_buy.py (~480줄)
- Top 3 추천: 메달 아이콘, composite_score, R/R 비율
- **분석 실행 버튼: st.progress() + try/except (st.spinner 아님!)**
- 오늘의 추천: 인덱스 탭 5개 (전체/NASDAQ100/S&P500/MIDCAP/SMALLCAP)
- 섹터 분포: plotly 도넛 차트
- 추천 이력: 기간/액션 필터 + 50행 페이지네이션
- AI 성과: 5개 메트릭 + 액션별/월별 plotly 바 차트

### dashboard/pages/ai_sell.py (~250줄)
- **분석 버튼 1개만** (중복 제거)
- 요약 메트릭 3개 (보유수, SELL수, 평균신뢰도)
- 매도 신호 카드: 긴급도 아이콘, 4개 스코어 progress bar, 출구전략 뱃지
- 전체 보유 현황: 상태별 확장/축소

### dashboard/pages/chart.py (~350줄)
- 티커 검색 + 기간 선택
- 6개 지표 메트릭 (RSI, MACD, vs MA20/50, ADX, StochRSI) — **safe_div() 적용**
- 7행 plotly 차트: 캔들+MA+BB / MACD / RSI / 거래량 / ADX / StochRSI / OBV

### dashboard/pages/news.py (~150줄)
- 인덱스 탭 3개 (전체/NASDAQ100/S&P500)
- **단일 `_render_news_list()` 함수** (중복 제거)
- 감성 요약: 전체건수, 평균감성, 긍정/부정 건수

### dashboard/pages/portfolio.py (~450줄)
- 5개 요약 메트릭
- 보유 테이블 (RdYlGn 그라디언트) + 도넛 차트 + CSV 다운로드
- 매수/매도/삭제 3탭 폼 — **입력 검증** (ticker 유효성, quantity>0, price>0)
- 알림 설정 + 7일 이력
- 성과 분석: 거래이력, 월별 PnL 차트, 섹터 배분, SPY YTD 비교

---

## 18. Docker 구성

### Dockerfile
Python 3.11, requirements.txt 설치, /app 작업 디렉토리

### docker-compose.yml
**2개 서비스:**

```yaml
scheduler:
  command: python main.py run
  volumes: data + logs
  restart: always
  stop_grace_period: 60s
  mem_limit: 2g
  healthcheck: DB 파일 존재 확인 (start_period: 120s)

dashboard:
  command: streamlit run dashboard/app.py --server.port=8085 --server.address=0.0.0.0 --server.headless=true
  ports: 8085:8085
  depends_on: scheduler (service_healthy)
  mem_limit: 2g
```

---

## 19. requirements.txt

```
yfinance>=1.2.0
pandas==2.2.3
numpy==2.2.2
SQLAlchemy==2.0.37
alembic==1.14.1
APScheduler==3.10.4
google-genai>=1.0.0
google-api-core>=2.14.0
streamlit==1.41.1
plotly==5.24.1
python-dotenv==1.0.1
requests==2.32.3
httpx==0.28.1
ta==0.11.0
loguru==0.7.3
vaderSentiment>=3.3.2
pytz==2025.1
tqdm==4.67.1
```

---

## 구현 우선순위

1. **Phase 1:** config + database + data_fetcher (데이터 파이프라인)
2. **Phase 2:** analysis (기술지표 + AI 매수/매도 + 리스크 + 백테스트)
3. **Phase 3:** portfolio + notifications (매매관리 + 알림)
4. **Phase 4:** dashboard (Streamlit UI)
5. **Phase 5:** scheduler + main.py (자동화 + CLI)
6. **Phase 6:** Docker + 배포

---

## 주의사항

- **google-genai** SDK 사용 (google-generativeai 아님)
- SQLite WAL 모드 + busy_timeout=5000 필수 (scheduler/dashboard 동시 접근)
- analyze_all_watchlist()는 매번 오늘 기존 분석 삭제 후 재분석
- Streamlit pages/ 폴더 자동 네비게이션 CSS로 숨김 필수
- 모든 AI 응답은 JSON 파싱 + regex 폴백 + 범위 검증 필수
- 5-Factor 스코어링의 VIX 레짐/ADX 마이크로레짐 로직 정확히 구현
- Trailing Stop: dynamic_threshold = max(3×ATR/현재가, 5%) clamp 20%
