"""Intelligence scan orchestration tests."""

from unittest.mock import patch

from core import orchestrator


def test_intelligence_scan_background_returns_immediately():
    with patch.object(orchestrator._executor, "submit") as mock_submit:
        result = orchestrator.trigger_intelligence_scan_background()
        assert result["success"] is True
        assert result["status"] == "started"
        mock_submit.assert_called_once()


def test_intelligence_scan_busy_when_already_running():
    orchestrator._scan_running = True
    try:
        result = orchestrator.trigger_intelligence_scan_background()
        assert result["success"] is False
        assert result["status"] == "busy"
    finally:
        orchestrator._scan_running = False


def test_intelligence_scan_can_start_while_backup_running():
    orchestrator._backup_running = True
    try:
        with patch.object(orchestrator._executor, "submit"):
            result = orchestrator.trigger_intelligence_scan_background()
            assert result["success"] is True
    finally:
        orchestrator._backup_running = False
