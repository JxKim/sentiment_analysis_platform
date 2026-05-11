"""
Report Engine service layer — framework-agnostic business logic.

Extracted from ReportEngine during Phase 2 migration.
Manages task lifecycle, SSE subscribers, log streaming, and report generation.
"""

import os
import json
import sys
import threading
import time
from collections import deque, defaultdict
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Dict, Any, List, Optional, Callable

from loguru import logger

# 确保 engines/ 和 app/ 在 Python 路径中，使 ReportEngine 等模块可被导入
_root = Path(__file__).resolve().parent.parent.parent
_engines_path = str(_root / "engines")
if _engines_path not in sys.path:
    sys.path.insert(0, _engines_path)
_app_path = str(_root / "app")
if _app_path not in sys.path:
    sys.path.insert(0, _app_path)

# ── Constants ──────────────────────────────────────────────────────────────

MAX_TASK_HISTORY = 5
STREAM_HEARTBEAT_INTERVAL = 15
STREAM_IDLE_TIMEOUT = 120
STREAM_TERMINAL_STATUSES = {"completed", "error", "cancelled"}
EXCLUDED_ENGINE_PATH_KEYWORDS = ("ForumEngine", "InsightEngine", "MediaEngine", "QueryEngine")
LOG_STREAM_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# ── Global state ───────────────────────────────────────────────────────────

current_task: Optional["ReportTask"] = None
task_lock = threading.Lock()
stream_lock = threading.Lock()
stream_subscribers: Dict[str, List[Queue]] = defaultdict(list)
tasks_registry: Dict[str, "ReportTask"] = {}
log_stream_handler_id: Optional[int] = None


# ── Log filtering ──────────────────────────────────────────────────────────

def _is_excluded_engine_log(record: Dict[str, Any]) -> bool:
    try:
        file_path = record["file"].path
        if any(keyword in file_path for keyword in EXCLUDED_ENGINE_PATH_KEYWORDS):
            return True
    except Exception:
        pass
    try:
        module_name = record.get("module", "")
        if isinstance(module_name, str):
            lowered = module_name.lower()
            return any(keyword.lower() in lowered for keyword in EXCLUDED_ENGINE_PATH_KEYWORDS)
    except Exception:
        pass
    return False


# ── Log → SSE forwarding ───────────────────────────────────────────────────

def _stream_log_to_task(message):
    try:
        record = message.record
        level_name = record["level"].name
        if level_name not in LOG_STREAM_LEVELS:
            return
        if _is_excluded_engine_log(record):
            return

        with task_lock:
            task = current_task

        if not task or task.status not in ("running", "pending"):
            return

        timestamp = record["time"].strftime("%H:%M:%S.%f")[:-3]
        formatted_line = f"[{timestamp}] [{level_name}] {record['message']}"
        task.publish_event(
            "log",
            {
                "line": formatted_line,
                "level": level_name.lower(),
                "timestamp": timestamp,
                "message": record["message"],
                "module": record.get("module", ""),
                "function": record.get("function", ""),
            },
        )
    except Exception:
        pass


def _setup_log_stream_forwarder():
    global log_stream_handler_id
    if log_stream_handler_id is not None:
        return
    log_stream_handler_id = logger.add(
        _stream_log_to_task,
        level="DEBUG",
        enqueue=False,
        catch=True,
    )


# ── SSE subscriber management ──────────────────────────────────────────────

def _register_stream(task_id: str) -> Queue:
    queue = Queue()
    with stream_lock:
        stream_subscribers[task_id].append(queue)
    return queue


def _unregister_stream(task_id: str, queue: Queue):
    with stream_lock:
        listeners = stream_subscribers.get(task_id, [])
        if queue in listeners:
            listeners.remove(queue)
        if not listeners and task_id in stream_subscribers:
            stream_subscribers.pop(task_id, None)


def _broadcast_event(task_id: str, event: Dict[str, Any]):
    with stream_lock:
        listeners = list(stream_subscribers.get(task_id, []))
    for queue in listeners:
        try:
            queue.put(event, timeout=0.1)
        except Exception:
            logger.exception("推送流式事件失败，跳过当前监听队列")


def _prune_task_history_locked():
    if len(tasks_registry) <= MAX_TASK_HISTORY:
        return
    sorted_tasks = sorted(tasks_registry.values(), key=lambda t: t.created_at)
    for task in sorted_tasks[:-MAX_TASK_HISTORY]:
        tasks_registry.pop(task.task_id, None)


def _get_task(task_id: str) -> Optional["ReportTask"]:
    with task_lock:
        if current_task and current_task.task_id == task_id:
            return current_task
        return tasks_registry.get(task_id)


def _format_sse(event: Dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False)
    event_id = event.get("id", 0)
    event_type = event.get("type", "message")
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload}\n\n"


def _safe_filename_segment(value: str, fallback: str = "report") -> str:
    sanitized = "".join(c for c in str(value) if c.isalnum() or c in (" ", "-", "_")).strip()
    sanitized = sanitized.replace(" ", "_")
    return sanitized or fallback


# ── ReportTask ─────────────────────────────────────────────────────────────

class ReportTask:
    """
    报告生成任务。

    该对象串联运行状态、进度、事件历史及最终文件路径，
    既供后台线程更新，也供HTTP接口读取。
    """

    def __init__(self, query: str, task_id: str, custom_template: str = ""):
        self.task_id = task_id
        self.query = query
        self.custom_template = custom_template
        self.status = "pending"
        self.progress = 0
        self.result = None
        self.error_message = ""
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.html_content = ""
        self.report_file_path = ""
        self.report_file_relative_path = ""
        self.report_file_name = ""
        self.state_file_path = ""
        self.state_file_relative_path = ""
        self.ir_file_path = ""
        self.ir_file_relative_path = ""
        self.markdown_file_path = ""
        self.markdown_file_relative_path = ""
        self.markdown_file_name = ""
        self.event_history: deque = deque(maxlen=10000)
        self._event_lock = threading.Lock()
        self.last_event_id = 0

    def update_status(self, status: str, progress: int = None, error_message: str = ""):
        self.status = status
        if progress is not None:
            self.progress = progress
        if error_message:
            self.error_message = error_message
        self.updated_at = datetime.now()
        self.publish_event(
            "status",
            {
                "status": self.status,
                "progress": self.progress,
                "error_message": self.error_message,
                "hint": error_message or "",
                "task": self.to_dict(),
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "query": self.query,
            "status": self.status,
            "progress": self.progress,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "has_result": bool(self.html_content),
            "report_file_ready": bool(self.report_file_path),
            "report_file_name": self.report_file_name,
            "report_file_path": self.report_file_relative_path or self.report_file_path,
            "state_file_ready": bool(self.state_file_path),
            "state_file_path": self.state_file_relative_path or self.state_file_path,
            "ir_file_ready": bool(self.ir_file_path),
            "ir_file_path": self.ir_file_relative_path or self.ir_file_path,
            "markdown_file_ready": bool(self.markdown_file_path),
            "markdown_file_name": self.markdown_file_name,
            "markdown_file_path": self.markdown_file_relative_path or self.markdown_file_path,
        }

    def publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        timestamp = datetime.utcnow().isoformat() + "Z"
        event: Dict[str, Any] = {
            "id": 0,
            "type": event_type,
            "task_id": self.task_id,
            "timestamp": timestamp,
            "payload": payload,
        }
        with self._event_lock:
            self.last_event_id += 1
            event["id"] = self.last_event_id
            self.event_history.append(event)
        _broadcast_event(self.task_id, event)

    def history_since(self, last_event_id: Optional[int]) -> List[Dict[str, Any]]:
        with self._event_lock:
            if last_event_id is None:
                return list(self.event_history)
            return [evt for evt in self.event_history if evt["id"] > last_event_id]


# ── Engine initialization ──────────────────────────────────────────────────

def initialize_report_engine() -> bool:
    """Initialize ReportEngine log forwarder (idempotent)."""
    try:
        _setup_log_stream_forwarder()
        try:
            from ReportEngine.utils.dependency_check import log_dependency_status
            log_dependency_status()
        except Exception as dep_err:
            logger.warning(f"依赖检测失败: {dep_err}")
        logger.info("Report Engine初始化成功")
        return True
    except Exception as e:
        logger.exception(f"Report Engine初始化失败: {str(e)}")
        return False


# ── Input file checks ──────────────────────────────────────────────────────

def check_engines_ready() -> Dict[str, Any]:
    """Check if input files from all engines are ready."""
    import os
    directories = {
        "insight": "insight_reports",
        "media": "media_reports",
        "query": "query_reports",
    }
    forum_log_path = "logs/forum.log"

    files_found, missing_files = [], []
    latest_files: Dict[str, str] = {}
    has_any_engine = False

    for engine, directory in directories.items():
        if os.path.exists(directory):
            md_files = [f for f in os.listdir(directory) if f.endswith('.md')]
            if md_files:
                files_found.append(f"{engine}: {len(md_files)} 个文件")
                latest = max(md_files, key=lambda x: os.path.getmtime(os.path.join(directory, x)))
                latest_files[engine] = os.path.join(directory, latest)
                has_any_engine = True
            else:
                missing_files.append(f"{engine}: 目录中没有 .md 文件")
        else:
            missing_files.append(f"{engine}: 目录不存在")

    forum_ready = os.path.exists(forum_log_path)
    if forum_ready:
        files_found.append(f"forum: {os.path.basename(forum_log_path)}")
        latest_files['forum'] = forum_log_path
    else:
        missing_files.append("forum: 日志文件不存在")

    return {
        'ready': has_any_engine and forum_ready,
        'files_found': files_found,
        'missing_files': missing_files,
        'latest_files': latest_files,
    }


def _load_input_files(file_paths: Dict[str, str]) -> Dict[str, Any]:
    """Load engine report files and forum log content."""
    content: Dict[str, Any] = {'reports': [], 'forum_logs': ''}
    for engine in ['query', 'media', 'insight']:
        if engine in file_paths:
            try:
                with open(file_paths[engine], 'r', encoding='utf-8') as f:
                    content['reports'].append(f.read())
            except Exception:
                content['reports'].append("")
        else:
            content['reports'].append("")
    if 'forum' in file_paths:
        try:
            with open(file_paths['forum'], 'r', encoding='utf-8') as f:
                content['forum_logs'] = f.read()
        except Exception:
            pass
    return content


# ── Report generation (background thread) ─────────────────────────────────

def run_report_generation(task: ReportTask, query: str, custom_template: str = ""):
    global current_task

    try:
        def stream_handler(event_type: str, payload: Dict[str, Any]):
            task.publish_event(event_type, payload)
            if event_type == "progress" and "progress" in payload:
                task.update_status("running", payload["progress"])

        task.update_status("running", 5)
        task.publish_event("stage", {"message": "任务已启动，正在检查输入文件", "stage": "prepare"})

        # 直接顺序执行：检查就绪 → 加载文件 → 调用 agent.generate_report
        check_result = check_engines_ready()
        if not check_result.get("ready", False):
            missing = check_result.get("missing_files", [])
            error_msg = f"输入文件未准备就绪: {missing}"
            task.update_status("error", 0, error_msg)
            return

        task.publish_event("stage", {"message": "输入文件检查通过，准备载入内容", "stage": "io_ready"})

        from ReportEngine.agent import generate_report

        latest_files = check_result.get("latest_files", {})
        content = _load_input_files(latest_files)

        task.publish_event("stage", {"message": "源数据加载完成，启动生成流程", "stage": "data_loaded"})

        generation_result = generate_report(
            query=query,
            reports=content.get("reports", []),
            forum_logs=content.get("forum_logs", ""),
            custom_template=custom_template,
            save_report=True,
            stream_handler=stream_handler,
            report_id=task.task_id,
        )

        if not isinstance(generation_result, dict):
            html_report = str(generation_result)
            saved_files = {}
        else:
            html_report = generation_result.get("html_content", "")
            saved_files = generation_result

        task.publish_event("stage", {"message": "报告生成完毕，准备持久化", "stage": "persist"})

        task.html_content = html_report
        task.report_file_path = saved_files.get("report_filepath", "")
        task.report_file_relative_path = saved_files.get("report_relative_path", "")
        task.report_file_name = saved_files.get("report_filename", "")
        task.state_file_path = saved_files.get("state_filepath", "")
        task.ir_file_path = saved_files.get("ir_filepath", "")

        task.publish_event("html_ready", {
            "message": "HTML渲染完成，可刷新预览",
            "report_file": task.report_file_relative_path or task.report_file_path,
            "state_file": task.state_file_path,
            "task": task.to_dict(),
        })
        task.update_status("completed", 100)
        task.publish_event("completed", {
            "message": "任务完成",
            "duration_seconds": (task.updated_at - task.created_at).total_seconds(),
            "report_file": task.report_file_relative_path or task.report_file_path,
            "task": task.to_dict(),
        })

    except Exception as e:
        logger.exception(f"报告生成过程中发生错误: {str(e)}")
        task.update_status("error", 0, str(e))
        task.publish_event("error", {
            "message": str(e),
            "stage": "failed",
            "task": task.to_dict(),
        })


# ── Task management helpers for API layer ────────────────────────────────

def create_task(query: str, custom_template: str = "") -> ReportTask:
    """Create a new ReportTask and register it. Returns the task."""
    global current_task

    with task_lock:
        if current_task and current_task.status == "running":
            raise RuntimeError("已有报告生成任务在运行中")
        if current_task and current_task.status in ["completed", "error"]:
            current_task = None

    task_id = f"report_{int(time.time())}"
    task = ReportTask(query, task_id, custom_template)

    with task_lock:
        current_task = task
        tasks_registry[task_id] = task
        _prune_task_history_locked()

    task.publish_event(
        "status",
        {
            "status": task.status,
            "progress": task.progress,
            "message": "任务已排队，等待资源空闲",
            "task": task.to_dict(),
        },
    )

    return task


def start_task_thread(task: ReportTask, query: str, custom_template: str = ""):
    """Launch background thread for report generation."""
    thread = threading.Thread(
        target=run_report_generation,
        args=(task, query, custom_template),
        daemon=True,
    )
    thread.start()


def cancel_task_by_id(task_id: str) -> bool:
    """Cancel a running task. Returns True if cancelled, False if not found."""
    global current_task

    with task_lock:
        if current_task and current_task.task_id == task_id:
            if current_task.status == "running":
                current_task.update_status("cancelled", 0, "用户取消任务")
                current_task.publish_event("cancelled", {
                    "message": "任务被用户主动终止",
                    "task": current_task.to_dict(),
                })
            current_task = None
        task = tasks_registry.get(task_id)
        if task and task.status == "running":
            task.update_status("cancelled", task.progress, "用户取消任务")
            task.publish_event("cancelled", {
                "message": "任务被用户主动终止",
                "task": task.to_dict(),
            })
            return True
        return False


def get_status_dict() -> Dict[str, Any]:
    """Build status response dict for the /status endpoint."""
    engines_status = check_engines_ready()
    with task_lock:
        task_dict = current_task.to_dict() if current_task else None
    return {
        "initialized": True,
        "engines_ready": engines_status["ready"],
        "files_found": engines_status.get("files_found", []),
        "missing_files": engines_status.get("missing_files", []),
        "current_task": task_dict,
    }


def get_templates_list() -> Dict[str, Any]:
    """Get available templates list."""
    from ReportEngine.utils.config import settings

    template_dir = settings.TEMPLATE_DIR
    templates = []

    if os.path.exists(template_dir):
        for filename in os.listdir(template_dir):
            if filename.endswith(".md"):
                template_path = os.path.join(template_dir, filename)
                try:
                    with open(template_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    templates.append({
                        "name": filename.replace(".md", ""),
                        "filename": filename,
                        "description": content.split("\n")[0] if content else "无描述",
                        "size": len(content),
                    })
                except Exception as e:
                    logger.exception(f"读取模板失败 {filename}: {str(e)}")

    return {"templates": templates, "template_dir": template_dir}


# ── Log management ─────────────────────────────────────────────────────────

def clear_report_log():
    """Clear report.log for a fresh task run."""
    from ReportEngine.utils.config import settings

    log_file = settings.LOG_FILE
    try:
        with open(log_file, "r+", encoding="utf-8") as f:
            f.truncate(0)
            f.flush()
        logger.info(f"已清空日志文件: {log_file}")
    except FileNotFoundError:
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("")
            logger.info(f"创建日志文件: {log_file}")
        except Exception as e:
            logger.exception(f"创建日志文件失败: {str(e)}")
    except Exception as e:
        logger.exception(f"清空日志文件失败: {str(e)}")


def get_report_log_lines() -> List[str]:
    """Read report.log lines, returns list of stripped non-empty strings."""
    from ReportEngine.utils.config import settings

    log_file = settings.LOG_FILE
    if not os.path.exists(log_file):
        return []

    file_size = os.path.getsize(log_file)
    max_size = 10 * 1024 * 1024

    if file_size > max_size:
        with open(log_file, "rb") as f:
            f.seek(-max_size, 2)
            f.readline()
            content = f.read().decode("utf-8", errors="replace")
        lines = content.splitlines()
        logger.warning(f"日志文件过大 ({file_size} bytes)，仅返回最后 {max_size} bytes")
    else:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

    return [line.rstrip("\n\r") for line in lines if line.strip()]


# ── Export helpers ─────────────────────────────────────────────────────────

def export_markdown_for_task(task_id: str) -> Dict[str, Any]:
    """Generate Markdown from IR and return file info dict."""
    task = tasks_registry.get(task_id)
    if not task:
        raise LookupError("任务不存在")

    if task.status != "completed":
        raise RuntimeError(f"任务未完成，当前状态: {task.status}")

    if not task.ir_file_path or not os.path.exists(task.ir_file_path):
        raise FileNotFoundError("IR文件不存在，无法生成Markdown")

    with open(task.ir_file_path, "r", encoding="utf-8") as f:
        document_ir = json.load(f)

    from ReportEngine.renderers import MarkdownRenderer
    from ReportEngine.utils.config import settings

    renderer = MarkdownRenderer()
    markdown_text = renderer.render(document_ir, ir_file_path=task.ir_file_path)

    metadata = document_ir.get("metadata") if isinstance(document_ir, dict) else {}
    topic = (metadata or {}).get("topic") or (metadata or {}).get("title") or (metadata or {}).get("query") or task.query
    safe_topic = _safe_filename_segment(topic or "report")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{safe_topic}_{timestamp}.md"

    output_dir = Path(settings.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / filename
    md_path.write_text(markdown_text, encoding="utf-8")

    task.markdown_file_path = str(md_path.resolve())
    task.markdown_file_relative_path = os.path.relpath(task.markdown_file_path, os.getcwd())
    task.markdown_file_name = filename

    logger.info(f"导出Markdown完成: {md_path}")
    return {
        "file_path": task.markdown_file_path,
        "file_name": filename,
    }


def export_pdf_for_task(task_id: str, optimize: bool = True) -> bytes:
    """Generate PDF from IR and return bytes."""
    task = tasks_registry.get(task_id)
    if not task:
        raise LookupError("任务不存在")

    if task.status != "completed":
        raise RuntimeError(f"任务未完成，当前状态: {task.status}")

    if not task.ir_file_path or not os.path.exists(task.ir_file_path):
        raise FileNotFoundError("IR文件不存在")

    with open(task.ir_file_path, "r", encoding="utf-8") as f:
        document_ir = json.load(f)

    from ReportEngine.renderers import PDFRenderer

    renderer = PDFRenderer()
    logger.info(f"开始导出PDF，任务ID: {task_id}，布局优化: {optimize}")
    return renderer.render_to_bytes(document_ir, optimize_layout=optimize)


def export_pdf_from_ir(document_ir: Dict[str, Any], optimize: bool = True) -> bytes:
    """Generate PDF directly from IR dict, returns bytes."""
    from ReportEngine.renderers import PDFRenderer

    renderer = PDFRenderer()
    logger.info(f"从IR直接导出PDF，布局优化: {optimize}")
    return renderer.render_to_bytes(document_ir, optimize_layout=optimize)
