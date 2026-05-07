"""
测试 app/services/forum_service.py — 论坛日志服务
"""

from pathlib import Path
project_root = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import patch, MagicMock, mock_open

class TestParseForumLogLine:
    def test_parses_host_message(self):
        from app.services.forum_service import parse_forum_log_line
        r = parse_forum_log_line("[10:00:01] [HOST] 发言")
        assert r["type"] == "host"
        assert r["sender"] == "Forum Host"
        assert r["content"] == "发言"

    def test_parses_agent_message(self):
        from app.services.forum_service import parse_forum_log_line
        r = parse_forum_log_line("[10:00:02] [INSIGHT] 洞察")
        assert r["type"] == "agent"
        assert r["sender"] == "Insight Engine"
        assert r["source"] == "INSIGHT"

    def test_rejects_system(self):
        from app.services.forum_service import parse_forum_log_line
        assert parse_forum_log_line("[10:00:00] [SYSTEM] init") is None

    def test_rejects_empty(self):
        from app.services.forum_service import parse_forum_log_line
        assert parse_forum_log_line("[10:00:00] [HOST]  ") is None

    def test_rejects_invalid_source(self):
        from app.services.forum_service import parse_forum_log_line
        assert parse_forum_log_line("[10:00:00] [UNKNOWN] text") is None

    def test_no_match(self):
        from app.services.forum_service import parse_forum_log_line
        assert parse_forum_log_line("bad format") is None

    def test_escaped_newlines(self):
        from app.services.forum_service import parse_forum_log_line
        r = parse_forum_log_line("[10:00:00] [HOST] a\\nb")
        assert "\n" in r["content"]

    def test_media_agent(self):
        from app.services.forum_service import parse_forum_log_line
        r = parse_forum_log_line("[10:00:00] [MEDIA] media result")
        assert r["sender"] == "Media Engine"

    def test_query_agent(self):
        from app.services.forum_service import parse_forum_log_line
        r = parse_forum_log_line("[10:00:00] [QUERY] query result")
        assert r["sender"] == "Query Engine"

class TestGetForumLog:
    @patch("app.services.forum_service.Path.exists", return_value=True)
    def test_returns_parsed(self, mock_exists):
        from app.services.forum_service import get_forum_log
        content = "[10:00:01] [HOST] h\n[10:00:02] [INSIGHT] i\n"
        with patch("builtins.open", mock_open(read_data=content)):
            r = get_forum_log()
        assert r["total_lines"] == 2
        assert len(r["parsed_messages"]) == 2

    @patch("app.services.forum_service.Path.exists", return_value=False)
    def test_no_file(self, mock_exists):
        from app.services.forum_service import get_forum_log
        r = get_forum_log()
        assert r["total_lines"] == 0

