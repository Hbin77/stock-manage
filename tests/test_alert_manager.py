"""
alert_manager.py 단위 테스트
"""
import pytest
from unittest.mock import MagicMock, patch


# ── VALID_ALERT_TYPES 테스트 ───────────────────────────────────────────────────

def test_valid_alert_types_contents():
    """VALID_ALERT_TYPES는 정확히 3개의 유형을 포함"""
    from notifications.alert_manager import VALID_ALERT_TYPES
    assert VALID_ALERT_TYPES == {"STOP_LOSS", "TARGET_PRICE", "VOLUME_SURGE"}


def test_valid_alert_types_is_frozenset():
    """VALID_ALERT_TYPES는 frozenset이어야 함 (불변)"""
    from notifications.alert_manager import VALID_ALERT_TYPES
    assert isinstance(VALID_ALERT_TYPES, frozenset)


def test_valid_alert_types_immutable():
    """frozenset에 add/discard 시 AttributeError 발생"""
    from notifications.alert_manager import VALID_ALERT_TYPES
    with pytest.raises(AttributeError):
        VALID_ALERT_TYPES.add("NEW_TYPE")  # type: ignore


# ── set_alert 유효성 검사 테스트 ──────────────────────────────────────────────

def test_set_alert_invalid_type_returns_false():
    """존재하지 않는 alert_type → False 반환, DB 호출 없음"""
    from notifications.alert_manager import AlertManager
    am = AlertManager()

    with patch("notifications.alert_manager.get_db") as mock_get_db:
        result = am.set_alert("AAPL", "INVALID_TYPE", 100.0)

    assert result is False
    mock_get_db.assert_not_called()


def test_set_alert_valid_types_attempt_db():
    """유효한 alert_type은 DB 접근 시도 (종목 미존재 → False지만 DB는 호출됨)"""
    from notifications.alert_manager import AlertManager
    am = AlertManager()

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # 종목 없음

    with patch("notifications.alert_manager.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__ = lambda s: mock_db
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
        result = am.set_alert("FAKEXYZ", "STOP_LOSS", 50.0)

    assert result is False  # 종목 없으므로 False
    mock_get_db.assert_called_once()


# ── _AlertCondition 데이터클래스 테스트 ──────────────────────────────────────

def test_alert_condition_is_frozen():
    """_AlertCondition은 frozen dataclass — 필드 수정 시 FrozenInstanceError"""
    from notifications.alert_manager import _AlertCondition
    cond = _AlertCondition(alert_type="STOP_LOSS", threshold_value=100.0)

    with pytest.raises(Exception):  # FrozenInstanceError (dataclasses.FrozenInstanceError)
        cond.alert_type = "TARGET_PRICE"  # type: ignore


def test_alert_condition_fields():
    """_AlertCondition 필드 접근 정상 동작"""
    from notifications.alert_manager import _AlertCondition
    cond = _AlertCondition(alert_type="TARGET_PRICE", threshold_value=200.0)
    assert cond.alert_type == "TARGET_PRICE"
    assert cond.threshold_value == 200.0


def test_alert_condition_equality():
    """같은 값의 두 _AlertCondition은 동일"""
    from notifications.alert_manager import _AlertCondition
    a = _AlertCondition("STOP_LOSS", 100.0)
    b = _AlertCondition("STOP_LOSS", 100.0)
    assert a == b
