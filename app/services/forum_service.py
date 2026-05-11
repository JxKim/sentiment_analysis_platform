"""
Forum service — forum log monitoring, parsing, start/stop control.

Uses event_bus.publish() for real-time events.
"""

import re
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from app.services.event_bus import publish

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)

# Optional callback for framework-specific init
_on_init_forum_log: Optional[Callable[[], None]] = None

# Event-driven forum handler (global, replaces LogMonitor)
_forum_handler: Optional[Any] = None


def init_forum_log():
    """Initialize (clear) forum.log with a header line."""
    forum_log_file = LOG_DIR / "forum.log"
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(forum_log_file, 'w', encoding='utf-8') as f:
        f.write(f"=== ForumEngine 系统初始化 - {start_time} ===\n")
    logger.info("ForumEngine: forum.log 已初始化")


def start_forum_engine():
    global _forum_handler
    try:
        if _forum_handler is not None:
            return True
        from engines.ForumEngine.handler import ForumEventHandler
        _forum_handler = ForumEventHandler()
        _forum_handler.start()
        logger.info("ForumEngine: 论坛事件处理器已启动")
        return True
    except Exception as e:
        logger.exception(f"ForumEngine: 启动论坛失败: {e}")
        return False


def stop_forum_engine():
    global _forum_handler
    try:
        if _forum_handler is not None:
            _forum_handler.stop()
            _forum_handler = None
            logger.info("ForumEngine: 论坛已停止")
    except Exception as e:
        logger.exception(f"ForumEngine: 停止论坛失败: {e}")


def parse_forum_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a forum.log line into a structured message dict."""
    pattern = r'\[(\d{2}:\d{2}:\d{2})\]\s*\[([^\]]+)\]\s*(.*)'
    match = re.match(pattern, line)
    if not match:
        return None

    timestamp, raw_source, content = match.groups()
    source = raw_source.strip().upper()

    if source == 'SYSTEM' or not content.strip():
        return None
    if source not in ['QUERY', 'INSIGHT', 'MEDIA', 'HOST']:
        return None

    cleaned_content = content.replace('\\n', '\n').replace('\\r', '').strip()

    if source == 'HOST':
        message_type = 'host'
        sender = 'Forum Host'
    else:
        message_type = 'agent'
        sender = f'{source.title()} Engine'

    return {
        'type': message_type,
        'sender': sender,
        'content': cleaned_content,
        'timestamp': timestamp,
        'source': source,
    }


# Forum log tail monitor thread (started at import time, like original app.py)
_forum_monitor_started = False


def start_forum_log_monitor():
    """Start the daemon thread that tails forum.log and publishes events."""
    global _forum_monitor_started
    if _forum_monitor_started:
        return
    _forum_monitor_started = True
    t = threading.Thread(target=_monitor_forum_log, daemon=True)
    t.start()


def _monitor_forum_log():
    """Tail forum.log and publish forum_message + console_output events."""
    forum_log_file = LOG_DIR / "forum.log"
    last_position = 0
    processed_lines: set = set()

    if forum_log_file.exists():
        with open(forum_log_file, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)
            last_position = f.tell()

    while True:
        try:
            if forum_log_file.exists():
                with open(forum_log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(last_position)
                    new_lines = f.readlines()
                    if new_lines:
                        for line in new_lines:
                            line = line.rstrip('\n\r')
                            if line.strip():
                                line_hash = hash(line.strip())
                                if line_hash in processed_lines:
                                    continue
                                processed_lines.add(line_hash)

                                parsed = parse_forum_log_line(line)
                                if parsed:
                                    publish('forum_message', parsed)

                                timestamp = datetime.now().strftime('%H:%M:%S')
                                formatted = f"[{timestamp}] {line}"
                                publish('console_output', {'app': 'forum', 'line': formatted})

                        last_position = f.tell()

                        if len(processed_lines) > 1000:
                            recent = list(processed_lines)[-500:]
                            processed_lines = set(recent)
            time.sleep(1)
        except Exception:
            logger.exception("Forum日志监听错误")
            time.sleep(5)


def get_forum_log() -> Dict[str, Any]:
    """Read full forum.log and return raw lines + parsed messages."""
    forum_log_file = LOG_DIR / "forum.log"
    if not forum_log_file.exists():
        return {'log_lines': [], 'parsed_messages': [], 'total_lines': 0}

    with open(forum_log_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [line.rstrip('\n\r') for line in f.readlines() if line.strip()]

    parsed_messages = []
    for line in lines:
        msg = parse_forum_log_line(line)
        if msg:
            parsed_messages.append(msg)

    return {'log_lines': lines, 'parsed_messages': parsed_messages, 'total_lines': len(lines)}


def get_forum_log_history(position: int = 0, max_lines: int = 1000) -> Dict[str, Any]:
    """Read forum.log from a given byte position, returning up to max_lines."""
    forum_log_file = LOG_DIR / "forum.log"
    if not forum_log_file.exists():
        return {'log_lines': [], 'position': 0, 'has_more': False}

    lines: List[str] = []
    line_count = 0
    with open(forum_log_file, 'r', encoding='utf-8', errors='ignore') as f:
        f.seek(position)
        for line in f:
            if line_count >= max_lines:
                break
            line = line.rstrip('\n\r')
            if line.strip():
                timestamp = datetime.now().strftime('%H:%M:%S')
                lines.append(f"[{timestamp}] {line}")
                line_count += 1
        current_position = f.tell()
        f.seek(0, 2)
        end_position = f.tell()
        has_more = current_position < end_position

    return {'log_lines': lines, 'position': current_position, 'has_more': has_more}
