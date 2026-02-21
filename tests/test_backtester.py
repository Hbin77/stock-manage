"""
backtester.py 단위 테스트
DB 없이 순수 로직만 검증합니다.
"""
import pytest
from unittest.mock import MagicMock, patch


# ── _group_stats 테스트 ────────────────────────────────────────────────────────

def test_group_stats_all_wins():
    """모두 양수 수익률이면 win_rate=100.0"""
    from analysis.backtester import Backtester
    bt = Backtester()
    result = bt._group_stats([1.0, 2.5, 10.0])
    assert result["win_rate"] == 100.0
    assert result["avg_return"] == pytest.approx((1.0 + 2.5 + 10.0) / 3, rel=1e-4)


def test_group_stats_no_wins():
    """모두 음수 수익률이면 win_rate=0.0"""
    from analysis.backtester import Backtester
    bt = Backtester()
    result = bt._group_stats([-1.0, -2.5, -10.0])
    assert result["win_rate"] == 0.0
    assert result["avg_return"] < 0


def test_group_stats_mixed():
    """절반 양수이면 win_rate=50.0"""
    from analysis.backtester import Backtester
    bt = Backtester()
    result = bt._group_stats([5.0, -5.0, 3.0, -3.0])
    assert result["win_rate"] == 50.0


def test_group_stats_avg_return_precision():
    """avg_return은 소수점 4자리까지 반올림"""
    from analysis.backtester import Backtester
    bt = Backtester()
    result = bt._group_stats([1.0 / 3.0])  # 0.33333...
    assert result["avg_return"] == pytest.approx(0.3333, rel=1e-3)


# ── get_accuracy_stats 빈 DB 테스트 ───────────────────────────────────────────

def test_get_accuracy_stats_empty():
    """DB에 추천 데이터 없으면 모든 통계 필드가 None"""
    from analysis.backtester import Backtester
    bt = Backtester()

    mock_db = MagicMock()
    mock_db.query.return_value.join.return_value.filter.return_value.all.return_value = []

    with patch("analysis.backtester.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        result = bt.get_accuracy_stats(days=90)

    assert result["total_recommendations"] == 0
    assert result["with_outcomes"] == 0
    assert result["win_rate"] is None
    assert result["avg_return"] is None
    assert result["best_ticker"] is None
    assert result["sharpe_proxy"] is None


# ── update_outcomes 가드 테스트 ───────────────────────────────────────────────

def test_update_outcomes_skips_zero_price():
    """price_at_recommendation=0 인 레코드는 건너뜀"""
    from analysis.backtester import Backtester
    bt = Backtester()

    fake_rec = MagicMock()
    fake_rec.outcome_return = None
    fake_rec.price_at_recommendation = 0.0   # ← 0 가격
    fake_rec.recommendation_date = __import__("datetime").datetime(2020, 1, 1)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [fake_rec]

    with patch("analysis.backtester.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        n = bt.update_outcomes()

    # 가격이 0이므로 업데이트 없음
    assert n == 0


def test_update_outcomes_skips_negative_price():
    """price_at_recommendation < 0 인 레코드도 건너뜀"""
    from analysis.backtester import Backtester
    bt = Backtester()

    fake_rec = MagicMock()
    fake_rec.outcome_return = None
    fake_rec.price_at_recommendation = -5.0
    fake_rec.recommendation_date = __import__("datetime").datetime(2020, 1, 1)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [fake_rec]

    with patch("analysis.backtester.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        n = bt.update_outcomes()

    assert n == 0
