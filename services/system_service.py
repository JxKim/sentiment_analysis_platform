"""
System service — process management, config, system state.

Extracted from app.py to be framework-agnostic.
Both Flask (app.py) and FastAPI (routers/) import from here.
"""

import os
import sys
import subprocess
import time
import threading
import importlib
import atexit
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from loguru import logger

from services.event_bus import publish

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_MODULE_NAME = 'config'
CONFIG_FILE_PATH = PROJECT_ROOT / 'config.py'
CONFIG_KEYS = [
    'HOST', 'PORT',
    'DB_DIALECT', 'DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME', 'DB_CHARSET',
    'INSIGHT_ENGINE_API_KEY', 'INSIGHT_ENGINE_BASE_URL', 'INSIGHT_ENGINE_MODEL_NAME',
    'MEDIA_ENGINE_API_KEY', 'MEDIA_ENGINE_BASE_URL', 'MEDIA_ENGINE_MODEL_NAME',
    'QUERY_ENGINE_API_KEY', 'QUERY_ENGINE_BASE_URL', 'QUERY_ENGINE_MODEL_NAME',
    'REPORT_ENGINE_API_KEY', 'REPORT_ENGINE_BASE_URL', 'REPORT_ENGINE_MODEL_NAME',
    'FORUM_HOST_API_KEY', 'FORUM_HOST_BASE_URL', 'FORUM_HOST_MODEL_NAME',
    'KEYWORD_OPTIMIZER_API_KEY', 'KEYWORD_OPTIMIZER_BASE_URL', 'KEYWORD_OPTIMIZER_MODEL_NAME',
    'TAVILY_API_KEY', 'SEARCH_TOOL_TYPE', 'BOCHA_WEB_SEARCH_API_KEY', 'ANSPIRE_API_KEY',
    'GRAPHRAG_ENABLED', 'GRAPHRAG_MAX_QUERIES',
]


def _load_config_module():
    importlib.invalidate_caches()
    module = sys.modules.get(CONFIG_MODULE_NAME)
    try:
        if module is None:
            module = importlib.import_module(CONFIG_MODULE_NAME)
        else:
            module = importlib.reload(module)
    except ModuleNotFoundError:
        return None
    return module


def read_config_values() -> Dict[str, str]:
    try:
        import config as config_module
        config_module.reload_settings()
        current_settings = config_module.settings
        values = {}
        for key in CONFIG_KEYS:
            value = getattr(current_settings, key, None)
            values[key] = '' if value is None else str(value)
        return values
    except Exception:
        logger.exception("读取配置失败")
        return {}


def write_config_values(updates: Dict[str, Any]) -> None:
    project_root = PROJECT_ROOT
    env_file_path = project_root / ".env"

    env_lines: List[str] = []
    env_key_indices: Dict[str, int] = {}
    if env_file_path.exists():
        env_lines = env_file_path.read_text(encoding='utf-8').splitlines()
        for i, line in enumerate(env_lines):
            line_stripped = line.strip()
            if line_stripped and not line_stripped.startswith('#') and '=' in line_stripped:
                key = line_stripped.split('=')[0].strip()
                env_key_indices[key] = i

    for key, raw_value in updates.items():
        if raw_value is None or raw_value == '':
            env_value = ''
        elif isinstance(raw_value, (int, float)):
            env_value = str(raw_value)
        elif isinstance(raw_value, bool):
            env_value = 'True' if raw_value else 'False'
        else:
            value_str = str(raw_value)
            if ' ' in value_str or '\n' in value_str or '#' in value_str:
                escaped = value_str.replace('\\', '\\\\').replace('"', '\\"')
                env_value = f'"{escaped}"'
            else:
                env_value = value_str

        if key in env_key_indices:
            env_lines[env_key_indices[key]] = f'{key}={env_value}'
        else:
            env_lines.append(f'{key}={env_value}')

    env_file_path.parent.mkdir(parents=True, exist_ok=True)
    env_file_path.write_text('\n'.join(env_lines) + '\n', encoding='utf-8')

    import config as config_module
    config_module.reload_settings()


# ---------------------------------------------------------------------------
# System state
# ---------------------------------------------------------------------------
_system_state_lock = threading.Lock()
_system_state: Dict[str, bool] = {
    'started': False,
    'starting': False,
    'shutdown_in_progress': False,
}


def _set_system_state(*, started: Optional[bool] = None, starting: Optional[bool] = None):
    with _system_state_lock:
        if started is not None:
            _system_state['started'] = started
        if starting is not None:
            _system_state['starting'] = starting


def _get_system_state() -> Dict[str, bool]:
    with _system_state_lock:
        return _system_state.copy()


def _prepare_system_start() -> Tuple[bool, Optional[str]]:
    with _system_state_lock:
        if _system_state['started']:
            return False, '系统已启动'
        if _system_state['starting']:
            return False, '系统正在启动'
        _system_state['starting'] = True
        return True, None


def _mark_shutdown_requested() -> bool:
    with _system_state_lock:
        if _system_state.get('shutdown_in_progress'):
            return False
        _system_state['shutdown_in_progress'] = True
        return True


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------
processes: Dict[str, Dict[str, Any]] = {
    'insight': {'process': None, 'port': 8501, 'status': 'stopped', 'output': [], 'log_file': None, 'healthcheck_started_at': None},
    'media':   {'process': None, 'port': 8502, 'status': 'stopped', 'output': [], 'log_file': None, 'healthcheck_started_at': None},
    'query':   {'process': None, 'port': 8503, 'status': 'stopped', 'output': [], 'log_file': None, 'healthcheck_started_at': None},
    'forum':   {'process': None, 'port': None, 'status': 'stopped', 'output': [], 'log_file': None},
}

STREAMLIT_SCRIPTS = {
    'insight': 'SingleEngineApp/insight_engine_streamlit_app.py',
    'media':   'SingleEngineApp/media_engine_streamlit_app.py',
    'query':   'SingleEngineApp/query_engine_streamlit_app.py',
}

HEALTHCHECK_PATH = "/_stcore/health"
HEALTHCHECK_PROXIES = {'http': None, 'https': None}
HEALTHCHECK_GRACE_SECONDS = 15


def _build_healthcheck_url(port: int) -> str:
    return f"http://127.0.0.1:{port}{HEALTHCHECK_PATH}"


def _healthcheck_grace_active(app_name: str) -> bool:
    started_at = processes.get(app_name, {}).get('healthcheck_started_at')
    if not started_at:
        return False
    return (time.time() - started_at) < HEALTHCHECK_GRACE_SECONDS


def _log_healthcheck_failure(app_name: str, exc: Exception):
    if _healthcheck_grace_active(app_name):
        logger.debug(f"正在启动{app_name}，请等待")
        return
    logger.warning(f"{app_name} 健康检查失败: {exc}")


def _log_shutdown_step(message: str):
    logger.info(f"[Shutdown] {message}")


def _describe_running_children() -> List[str]:
    running = []
    for name, info in processes.items():
        proc = info.get('process')
        if proc is not None and proc.poll() is None:
            port_desc = f", port={info.get('port')}" if info.get('port') else ""
            running.append(f"{name}(pid={proc.pid}{port_desc})")
    return running


def write_log_to_file(app_name: str, line: str):
    try:
        log_file_path = LOG_DIR / f"{app_name}.log"
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
            f.flush()
    except Exception:
        logger.exception(f"Error writing log for {app_name}")


def read_log_from_file(app_name: str, tail_lines: Optional[int] = None) -> List[str]:
    try:
        log_file_path = LOG_DIR / f"{app_name}.log"
        if not log_file_path.exists():
            return []
        with open(log_file_path, 'r', encoding='utf-8') as f:
            lines = [line.rstrip('\n\r') for line in f.readlines() if line.strip()]
            if tail_lines:
                return lines[-tail_lines:]
            return lines
    except Exception:
        logger.exception(f"Error reading log for {app_name}")
        return []


def _read_process_output(process: subprocess.Popen, app_name: str):
    """Read subprocess output line by line, write to log file, publish via event bus."""
    import select

    while True:
        try:
            if process.poll() is not None:
                remaining = process.stdout.read()
                if remaining:
                    for line in remaining.split('\n'):
                        line = line.strip()
                        if line:
                            timestamp = datetime.now().strftime('%H:%M:%S')
                            formatted = f"[{timestamp}] {line}"
                            write_log_to_file(app_name, formatted)
                            publish('console_output', {'app': app_name, 'line': formatted})
                break

            if sys.platform == 'win32':
                output = process.stdout.readline()
                if output:
                    line = output.strip()
                    if line:
                        timestamp = datetime.now().strftime('%H:%M:%S')
                        formatted = f"[{timestamp}] {line}"
                        write_log_to_file(app_name, formatted)
                        publish('console_output', {'app': app_name, 'line': formatted})
                else:
                    time.sleep(0.1)
            else:
                ready, _, _ = select.select([process.stdout], [], [], 0.1)
                if ready:
                    output = process.stdout.readline()
                    if output:
                        line = output.strip()
                        if line:
                            timestamp = datetime.now().strftime('%H:%M:%S')
                            formatted = f"[{timestamp}] {line}"
                            write_log_to_file(app_name, formatted)
                            publish('console_output', {'app': app_name, 'line': formatted})
        except Exception:
            error_msg = f"Error reading output for {app_name}"
            logger.exception(error_msg)
            write_log_to_file(app_name, f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
            break


def start_streamlit_app(app_name: str, script_path: str, port: int) -> Tuple[bool, str]:
    try:
        if processes[app_name]['process'] is not None:
            return False, "应用已经在运行"

        if not os.path.exists(script_path):
            return False, f"文件不存在: {script_path}"

        log_file_path = LOG_DIR / f"{app_name}.log"
        if log_file_path.exists():
            log_file_path.unlink()

        start_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 启动 {app_name} 应用..."
        write_log_to_file(app_name, start_msg)

        cmd = [
            sys.executable, '-m', 'streamlit', 'run',
            script_path,
            '--server.port', str(port),
            '--server.headless', 'true',
            '--browser.gatherUsageStats', 'false',
            '--logger.level', 'info',
            '--server.enableCORS', 'false',
        ]

        env = os.environ.copy()
        env.update({
            'PYTHONIOENCODING': 'utf-8',
            'PYTHONUTF8': '1',
            'LANG': 'en_US.UTF-8',
            'LC_ALL': 'en_US.UTF-8',
            'PYTHONUNBUFFERED': '1',
            'STREAMLIT_BROWSER_GATHER_USAGE_STATS': 'false',
        })

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            universal_newlines=False,
            cwd=os.getcwd(),
            env=env,
            encoding='utf-8',
            errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        )

        processes[app_name]['process'] = process
        processes[app_name]['status'] = 'starting'
        processes[app_name]['output'] = []
        processes[app_name]['healthcheck_started_at'] = time.time()

        output_thread = threading.Thread(
            target=_read_process_output, args=(process, app_name), daemon=True)
        output_thread.start()

        return True, f"{app_name} 应用启动中..."
    except Exception as e:
        error_msg = f"启动失败: {str(e)}"
        write_log_to_file(app_name, f"[{datetime.now().strftime('%H:%M:%S')}] {error_msg}")
        return False, error_msg


def stop_streamlit_app(app_name: str) -> Tuple[bool, str]:
    try:
        proc = processes[app_name]['process']
        if proc is None:
            _log_shutdown_step(f"{app_name} 未运行，跳过停止")
            return False, "应用未运行"

        try:
            pid = proc.pid
        except Exception:
            pid = 'unknown'

        _log_shutdown_step(f"正在停止 {app_name} (pid={pid})")
        proc.terminate()
        try:
            proc.wait(timeout=5)
            _log_shutdown_step(f"{app_name} 退出完成，returncode={proc.returncode}")
        except subprocess.TimeoutExpired:
            _log_shutdown_step(f"{app_name} 终止超时，尝试强制结束 (pid={pid})")
            proc.kill()
            proc.wait()
            _log_shutdown_step(f"{app_name} 已强制结束，returncode={proc.returncode}")

        processes[app_name]['process'] = None
        processes[app_name]['status'] = 'stopped'
        processes[app_name]['healthcheck_started_at'] = None
        return True, f"{app_name} 应用已停止"
    except Exception as e:
        _log_shutdown_step(f"{app_name} 停止失败: {e}")
        return False, f"停止失败: {str(e)}"


def check_app_status():
    for app_name, info in processes.items():
        if info['process'] is not None:
            if info['process'].poll() is None:
                try:
                    response = requests.get(
                        _build_healthcheck_url(info['port']),
                        timeout=2, proxies=HEALTHCHECK_PROXIES)
                    if response.status_code == 200:
                        info['status'] = 'running'
                    else:
                        info['status'] = 'starting'
                except Exception as exc:
                    _log_healthcheck_failure(app_name, exc)
                    info['status'] = 'starting'
            else:
                info['process'] = None
                info['status'] = 'stopped'
                info['healthcheck_started_at'] = None


def wait_for_app_startup(app_name: str, max_wait_time: int = 90) -> Tuple[bool, str]:
    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        info = processes[app_name]
        if info['process'] is None:
            return False, "进程已停止"
        if info['process'].poll() is not None:
            return False, "进程启动失败"
        try:
            response = requests.get(
                _build_healthcheck_url(info['port']),
                timeout=2, proxies=HEALTHCHECK_PROXIES)
            if response.status_code == 200:
                info['status'] = 'running'
                return True, "启动成功"
        except Exception as exc:
            _log_healthcheck_failure(app_name, exc)
        time.sleep(1)
    return False, "启动超时"


def cleanup_processes():
    _log_shutdown_step("开始串行清理子进程")
    for app_name in STREAMLIT_SCRIPTS:
        stop_streamlit_app(app_name)
    processes['forum']['status'] = 'stopped'
    try:
        from services.forum_service import stop_forum_engine
        stop_forum_engine()
    except Exception:
        logger.exception("停止ForumEngine失败")
    _log_shutdown_step("子进程清理完成")
    _set_system_state(started=False, starting=False)


def cleanup_processes_concurrent(timeout: float = 6.0):
    _log_shutdown_step(f"开始并发清理子进程（超时 {timeout}s）")
    running_before = _describe_running_children()
    if running_before:
        _log_shutdown_step("当前存活子进程: " + ", ".join(running_before))
    else:
        _log_shutdown_step("未检测到存活子进程，仍将发送关闭指令")

    threads = []
    for app_name in STREAMLIT_SCRIPTS:
        t = threading.Thread(target=stop_streamlit_app, args=(app_name,), daemon=True)
        threads.append(t)
        t.start()

    from services.forum_service import stop_forum_engine
    ft = threading.Thread(target=stop_forum_engine, daemon=True)
    threads.append(ft)
    ft.start()

    end_time = time.time() + timeout
    for t in threads:
        remaining = end_time - time.time()
        if remaining <= 0:
            break
        t.join(timeout=remaining)

    for app_name in STREAMLIT_SCRIPTS:
        proc = processes[app_name]['process']
        if proc is not None and proc.poll() is None:
            try:
                _log_shutdown_step(f"{app_name} 进程仍存活，触发二次终止 (pid={proc.pid})")
                proc.terminate()
                proc.wait(timeout=1)
            except Exception:
                try:
                    _log_shutdown_step(f"{app_name} 二次终止失败，尝试kill (pid={proc.pid})")
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    logger.warning(f"{app_name} 进程强制退出失败，继续关机")
            finally:
                processes[app_name]['process'] = None
                processes[app_name]['status'] = 'stopped'

    processes['forum']['status'] = 'stopped'
    _log_shutdown_step("并发清理结束，标记系统未启动")
    _set_system_state(started=False, starting=False)


def _schedule_server_shutdown(delay_seconds: float = 0.1, stop_callback=None):
    def _shutdown():
        time.sleep(delay_seconds)
        if stop_callback:
            stop_callback()
        _log_shutdown_step("服务器停止指令已发送，即将退出主进程")
        os._exit(0)
    threading.Thread(target=_shutdown, daemon=True).start()


def _start_async_shutdown(cleanup_timeout: float = 3.0, stop_callback=None):
    _log_shutdown_step(f"收到关机指令，启动异步清理（超时 {cleanup_timeout}s）")

    def _force_exit():
        _log_shutdown_step("关机超时，触发强制退出")
        os._exit(0)

    hard_timeout = cleanup_timeout + 2.0
    force_timer = threading.Timer(hard_timeout, _force_exit)
    force_timer.daemon = True
    force_timer.start()

    def _cleanup_and_exit():
        try:
            cleanup_processes_concurrent(timeout=cleanup_timeout)
        except Exception:
            logger.exception(f"关机清理异常")
        finally:
            _log_shutdown_step("清理线程结束，调度主进程退出")
            _schedule_server_shutdown(0.05, stop_callback)

    threading.Thread(target=_cleanup_and_exit, daemon=True).start()


def initialize_system_components() -> Tuple[bool, List[str], List[str]]:
    logs: List[str] = []
    errors: List[str] = []

    try:
        from SentinelSpider.main import SentinelSpider
        spider = SentinelSpider()
        if spider.initialize_database():
            logger.info("数据库初始化成功")
        else:
            logger.error("数据库初始化失败")
    except Exception as exc:
        logs.append(f"数据库初始化异常: {exc}")

    from services.forum_service import start_forum_engine, stop_forum_engine
    try:
        stop_forum_engine()
        logs.append("已停止 ForumEngine 监控器以避免文件冲突")
    except Exception as exc:
        message = f"停止 ForumEngine 时发生异常: {exc}"
        logs.append(message)
        logger.exception(message)

    processes['forum']['status'] = 'stopped'

    for app_name, script_path in STREAMLIT_SCRIPTS.items():
        logs.append(f"检查文件: {script_path}")
        if os.path.exists(script_path):
            success, message = start_streamlit_app(app_name, script_path, processes[app_name]['port'])
            logs.append(f"{app_name}: {message}")
            if success:
                startup_success, startup_message = wait_for_app_startup(app_name, 30)
                logs.append(f"{app_name} 启动检查: {startup_message}")
                if not startup_success:
                    errors.append(f"{app_name} 启动失败: {startup_message}")
            else:
                errors.append(f"{app_name} 启动失败: {message}")
        else:
            msg = f"文件不存在: {script_path}"
            logs.append(f"错误: {msg}")
            errors.append(f"{app_name}: {msg}")

    forum_started = False
    try:
        start_forum_engine()
        processes['forum']['status'] = 'running'
        logs.append("ForumEngine 启动完成")
        forum_started = True
    except Exception as exc:
        error_msg = f"ForumEngine 启动失败: {exc}"
        logs.append(error_msg)
        errors.append(error_msg)

    try:
        from services.report_service import initialize_report_engine
        if initialize_report_engine():
            logs.append("ReportEngine 初始化成功")
        else:
            msg = "ReportEngine 初始化失败"
            logs.append(msg)
            errors.append(msg)
    except Exception as exc:
        msg = f"ReportEngine 初始化异常: {exc}"
        logs.append(msg)
        errors.append(msg)

    if errors:
        cleanup_processes()
        processes['forum']['status'] = 'stopped'
        if forum_started:
            try:
                stop_forum_engine()
            except Exception:
                logger.exception("停止ForumEngine失败")
        return False, logs, errors

    return True, logs, []


# Register cleanup on exit
atexit.register(cleanup_processes)
