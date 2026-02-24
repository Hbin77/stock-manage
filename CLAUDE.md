# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# First-time setup: create DB tables, load 2-year historical data for all tickers
python main.py init

# Start APScheduler (10 background jobs: prices, AI analysis, alerts, backtesting)
python main.py run

# Manual triggers
python main.py analyze       # AI buy analysis (Gemini)
python main.py sell_check    # AI sell signal analysis
python main.py fetch         # Fetch prices + news
python main.py calc          # Recalculate technical indicators
python main.py status        # Print portfolio summary
python main.py notify_test   # Test Kakao/Telegram notifications

# Dashboard
streamlit run dashboard/app.py --server.port 8501

# Docker (NAS deployment)
docker-compose up -d --build
docker-compose logs -f scheduler
```

## Architecture

**Pipeline:** yfinance → MarketFetcher → SQLite DB → TechnicalAnalyzer → AI Analyzer (Gemini) → Notifications (Kakao/Telegram) → Streamlit Dashboard

### Key Modules
- `data_fetcher/market_data.py` — yfinance data collection, batch processing (100/batch)
- `data_fetcher/scheduler.py` — APScheduler with 10 jobs, NYSE trading hours only (America/New_York)
- `analysis/ai_analyzer.py` — Gemini 2.5 Flash buy recommendations (BUY/STRONG_BUY/HOLD)
- `analysis/sell_analyzer.py` — Gemini sell signals with 3-pillar scoring (tech 0.45 + position risk 0.35 + fundamental 0.20)
- `analysis/risk_manager.py` — Position sizing, sector concentration, portfolio loss limits
- `analysis/backtester.py` — Post-validates AI recommendations (5/10/30 day outcomes)
- `notifications/alert_manager.py` — Price alerts: STOP_LOSS, TARGET_PRICE, TRAILING_STOP, VOLUME_SURGE
- `portfolio/portfolio_manager.py` — Holdings, transactions, P&L tracking
- `dashboard/app.py` — Streamlit multi-page dashboard (password protected)

### Patterns
- **DB Access:** `with get_db() as db:` context manager (auto commit/rollback)
- **Singletons:** Module-level instances (e.g., `ai_analyzer = AIAnalyzer()`)
- **Logging:** `from loguru import logger`
- **Config:** `from config.settings import settings` — reads from `.env` via `os.getenv()`
- **AI SDK:** `google.genai` (new SDK, NOT deprecated `google.generativeai`)
- **Thinking model:** `types.ThinkingConfig(thinking_budget=1024)` to cap thinking tokens

### Database (SQLite WAL mode)
16 tables via SQLAlchemy ORM in `database/models.py`. Key tables: `stocks`, `price_history`, `technical_indicators`, `ai_recommendations`, `sell_signals`, `portfolio_holdings`, `transactions`, `price_alerts`, `alert_history`, `market_news`.

### Docker (2 services)
- `scheduler`: `python main.py run` (background jobs)
- `dashboard`: Streamlit on port 8085
- Volumes: `DATA_PATH` for SQLite DB, `LOG_PATH` for logs

### Ticker Universe
`config/tickers.py` defines ALL_TICKERS (~818 NASDAQ100 + S&P500 + ETFs). Watchlist priority: DB portfolio holdings > `WATCHLIST_TICKERS` env var > ALL_TICKERS fallback.
