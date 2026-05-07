"""
测试 app/services/ — event_bus, system_service, search_service
已验证可稳定运行的部分
"""

from pathlib import Path
project_root = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import patch, MagicMock, mock_open


class TestEventBus:
    def setup_method(self):
        from app.services import event_bus
        event_bus.clear()

    def test_publish_calls_subscriber(self):
        from app.services.event_bus import publish, subscribe
        received = []
        def cb(evt, data):
            received.append((evt, data))
        subscribe(cb)
        publish("test_event", {"key": "value"})
        assert len(received) == 1
        assert received[0] == ("test_event", {"key": "value"})

    def test_subscriber_error_does_not_propagate(self):
        from app.services.event_bus import publish, subscribe
        errors = []
        def bad_cb(evt, data):
            raise RuntimeError("oops")
        def good_cb(evt, data):
            errors.append("reached")
        subscribe(bad_cb)
        subscribe(good_cb)
        publish("test", {})
        assert errors == ["reached"]

    def test_unsubscribe(self):
        from app.services.event_bus import publish, subscribe, unsubscribe
        received = []
        def cb(evt, data):
            received.append(evt)
        subscribe(cb)
        unsubscribe(cb)
        publish("test", {})
        assert len(received) == 0

    def test_unsubscribe_non_existent(self):
        from app.services.event_bus import unsubscribe
        unsubscribe(lambda: None)

    def test_clear_removes_all(self):
        from app.services.event_bus import publish, subscribe, clear
        def cb(evt, data):
            pass
        subscribe(cb)
        clear()
        from app.services import event_bus
        assert len(event_bus._subscribers) == 0


class TestReadConfigValues:
    @patch("app.services.system_service.Path.exists", return_value=True)
    def test_returns_values(self, mock_exists):
        import sys
        mock_cfg_mod = MagicMock()
        mock_cfg_mod.settings = MagicMock(HOST="0.0.0.0", PORT=5000, DB_HOST="h")
        mock_cfg_mod.reload_settings = MagicMock()
        sys.modules["config"] = mock_cfg_mod
        from app.services.system_service import read_config_values
        values = read_config_values()
        assert values["HOST"] == "0.0.0.0"


class TestSystemState:
    def setup_method(self):
        from app.services.system_service import _set_system_state
        _set_system_state(started=False, starting=False)

    def test_initial_state(self):
        from app.services.system_service import _get_system_state
        assert _get_system_state()["started"] is False

    def test_set_started(self):
        from app.services.system_service import _set_system_state, _get_system_state
        _set_system_state(started=True)
        assert _get_system_state()["started"] is True

    def test_prepare_system_start_success(self):
        from app.services.system_service import _prepare_system_start
        ok, msg = _prepare_system_start()
        assert ok is True and msg is None

    def test_prepare_system_start_already_started(self):
        from app.services.system_service import _prepare_system_start, _set_system_state
        _set_system_state(started=True)
        ok, _ = _prepare_system_start()
        assert ok is False

    def test_prepare_system_start_starting(self):
        from app.services.system_service import _prepare_system_start, _set_system_state
        _set_system_state(starting=True)
        ok, _ = _prepare_system_start()
        assert ok is False

    def test_mark_shutdown_requested(self):
        from app.services.system_service import _mark_shutdown_requested
        assert _mark_shutdown_requested() is True
        assert _mark_shutdown_requested() is False


class TestReadWriteLog:
    @patch("app.services.system_service.Path.exists", return_value=True)
    def test_write_log(self, mock_exists):
        from app.services.system_service import write_log_to_file
        m = mock_open()
        with patch("builtins.open", m):
            write_log_to_file("test_app", "hello world")
        m().write.assert_called_once()

    @patch("app.services.system_service.Path.exists", return_value=True)
    def test_read_log(self, mock_exists):
        from app.services.system_service import read_log_from_file
        m = mock_open(read_data="line1\nline2\nline3\n")
        with patch("builtins.open", m):
            assert len(read_log_from_file("test_app")) == 3

    @patch("app.services.system_service.Path.exists", return_value=True)
    def test_read_log_tail(self, mock_exists):
        from app.services.system_service import read_log_from_file
        m = mock_open(read_data="line1\nline2\nline3\n")
        with patch("builtins.open", m):
            lines = read_log_from_file("test_app", tail_lines=2)
        assert lines == ["line2", "line3"]

    @patch("app.services.system_service.Path.exists", return_value=False)
    def test_read_log_file_not_found(self, mock_exists):
        from app.services.system_service import read_log_from_file
        assert read_log_from_file("nonexistent") == []

    def test_write_log_exception(self):
        from app.services.system_service import write_log_to_file
        with patch("builtins.open", side_effect=PermissionError("denied")):
            write_log_to_file("test", "data")


class TestSearchAll:
    @patch("app.services.search_service.run_engine_task")
    def test_launches_three_engines(self, mock_run):
        from app.services.search_service import search_all
        result = search_all("test query")
        assert result["success"] is True
        assert mock_run.call_count == 3

    @patch("app.services.search_service.run_engine_task")
    def test_empty_query(self, mock_run):
        from app.services.search_service import search_all
        result = search_all("  ")
        assert result["success"] is False
        mock_run.assert_not_called()


class TestExtractCitations:
    def test_extracts_from_paragraphs(self):
        from app.services.search_service import _extract_citations
        mock_agent = MagicMock()
        mock_para = MagicMock()
        mock_search = MagicMock(query="q", url="u", title="t", content="c", score=0.9)
        mock_para.title = "P1"
        mock_para.research.search_history = [mock_search]
        mock_para.research.get_search_count.return_value = 1
        mock_para.research.reflection_iteration = 0
        mock_agent.state.paragraphs = [mock_para]
        citations = _extract_citations(mock_agent)
        assert len(citations) == 1
        assert citations[0]["query"] == "q"

    def test_empty_state(self):
        from app.services.search_service import _extract_citations
        mock_agent = MagicMock()
        mock_agent.state.paragraphs = []
        assert _extract_citations(mock_agent) == []
