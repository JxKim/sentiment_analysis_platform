"""
Search service — runs Insight/Media/Query engine agents in background threads.
Publishes progress/results via event_bus SSE.

All engines use module-level run_research() directly.
"""

import threading
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from app.services.event_bus import publish
from app.services.event_types import EventType
from app.services.forum_service import start_forum_engine

OUTPUT_DIRS = {
    'insight': 'data/report/insight',
    'media': 'data/report/media',
    'query': 'data/report/query',
}
_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def search_all(query: str):
    """Launch all 3 engine tasks in parallel background threads."""
    if not query.strip():
        return {"success": False, "message": "搜索查询不能为空"}

    start_forum_engine()

    for engine_type in ['insight', 'media', 'query']:
        t = threading.Thread(
            target=run_engine_task,
            args=(engine_type, query),
            daemon=True,
        )
        t.start()

    return {"success": True, "message": "已启动所有引擎搜索", "query": query}


def run_engine_task(engine_type: str, query: str):
    """Run an engine agent in the current thread, publishing progress via SSE."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = str(_LOG_DIR / f"{engine_type}.log")
    _sink_id = logger.add(
        _log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} - {message}",
        level="INFO", encoding="utf-8", rotation="10 MB",
        filter=lambda record: engine_type in record["name"],
    )

    try:
        publish(EventType.ENGINE_PROGRESS, {
            "engine": engine_type, "status": "starting",
            "message": "正在初始化引擎...", "progress_pct": 0,
        })

        if engine_type == 'insight':
            result = _run_insight_research(query)
        elif engine_type == 'media':
            result = _run_media_research(query)
        elif engine_type == 'query':
            result = _run_query_research(query)
        else:
            raise ValueError(f"Unknown engine type: {engine_type}")

        final_report = result.get("final_report", "")
        citations = _extract_citations_from_result(result)

        publish(EventType.ENGINE_PROGRESS, {
            "engine": engine_type, "status": "finalizing",
            "message": "研究完成", "progress_pct": 100,
        })
        publish("engine_result", {
            "engine": engine_type, "final_report": final_report,
            "citations": citations,
        })

    except Exception as exc:
        import traceback
        logger.exception(f"{engine_type} engine error: {exc}")
        publish("engine_error", {
            "engine": engine_type, "error": str(exc),
            "traceback": traceback.format_exc(),
        })
    finally:
        try:
            logger.remove(_sink_id)
        except Exception:
            pass


def _run_insight_research(query: str) -> Dict[str, Any]:
    from app.config import settings, Settings
    from engines.InsightEngine.agent import run_research
    from engines.InsightEngine.llms import LLMClient

    model = settings.INSIGHT_ENGINE_MODEL_NAME or "kimi-k2-0711-preview"
    config = Settings(
        INSIGHT_ENGINE_API_KEY=settings.INSIGHT_ENGINE_API_KEY,
        INSIGHT_ENGINE_BASE_URL=settings.INSIGHT_ENGINE_BASE_URL,
        INSIGHT_ENGINE_MODEL_NAME=model,
        DB_HOST=settings.DB_HOST, DB_USER=settings.DB_USER,
        DB_PASSWORD=settings.DB_PASSWORD, DB_NAME=settings.DB_NAME,
        DB_PORT=settings.DB_PORT, DB_CHARSET=settings.DB_CHARSET,
        DB_DIALECT=settings.DB_DIALECT,
        MAX_REFLECTIONS=2, MAX_CONTENT_LENGTH=500000,
        OUTPUT_DIR=OUTPUT_DIRS['insight'],
    )
    llm_client = LLMClient(
        api_key=config.INSIGHT_ENGINE_API_KEY,
        model_name=config.INSIGHT_ENGINE_MODEL_NAME,
        base_url=config.INSIGHT_ENGINE_BASE_URL,
    )

    # 这里也是一种抽象，InsightEngine当中所有的节点的事件，event_type全部都是engine_progress，
    def progress_callback(data):
        "回调函数，用以通过SSE机制，在前端展示进度"
        publish(EventType.ENGINE_PROGRESS, {"engine": "insight", **data})

    return run_research(query, config, llm_client, progress_callback)


def _run_media_research(query: str) -> Dict[str, Any]:
    from app.config import settings, Settings
    from engines.MediaEngine.agent import run_research
    from engines.MediaEngine.llms import LLMClient
    from engines.MediaEngine.tools import (
        BochaMultimodalSearch, AnspireAISearch, TavilySearchWrapper,
    )

    model = settings.MEDIA_ENGINE_MODEL_NAME or "gemini-2.5-pro"
    search_type = settings.SEARCH_TOOL_TYPE or "TavilyAPI"
    config = Settings(
        MEDIA_ENGINE_API_KEY=settings.MEDIA_ENGINE_API_KEY,
        MEDIA_ENGINE_BASE_URL=settings.MEDIA_ENGINE_BASE_URL,
        MEDIA_ENGINE_MODEL_NAME=model,
        SEARCH_TOOL_TYPE=search_type,
        TAVILY_API_KEY=settings.TAVILY_API_KEY,
        BOCHA_WEB_SEARCH_API_KEY=settings.BOCHA_WEB_SEARCH_API_KEY,
        ANSPIRE_API_KEY=settings.ANSPIRE_API_KEY,
        MAX_REFLECTIONS=2, SEARCH_CONTENT_MAX_LENGTH=20000,
        OUTPUT_DIR=OUTPUT_DIRS['media'],
    )
    llm_client = LLMClient(
        api_key=config.MEDIA_ENGINE_API_KEY,
        model_name=config.MEDIA_ENGINE_MODEL_NAME,
        base_url=config.MEDIA_ENGINE_BASE_URL,
    )

    if search_type == "TavilyAPI":
        search_agency = TavilySearchWrapper(api_key=config.TAVILY_API_KEY)
    elif search_type == "AnspireAPI":
        search_agency = AnspireAISearch(api_key=config.ANSPIRE_API_KEY)
    else:
        search_agency = BochaMultimodalSearch(api_key=config.BOCHA_WEB_SEARCH_API_KEY)

    def progress_callback(data):
        publish(EventType.ENGINE_PROGRESS, {"engine": "media", **data})

    return run_research(query, config, llm_client, search_agency, progress_callback)


def _run_query_research(query: str) -> Dict[str, Any]:
    from app.config import settings, Settings
    from engines.QueryEngine.agent import run_research
    from engines.QueryEngine.llms import LLMClient
    from engines.QueryEngine.tools import TavilyNewsAgency

    model = settings.QUERY_ENGINE_MODEL_NAME or "deepseek-chat"
    config = Settings(
        QUERY_ENGINE_API_KEY=settings.QUERY_ENGINE_API_KEY,
        QUERY_ENGINE_BASE_URL=settings.QUERY_ENGINE_BASE_URL,
        QUERY_ENGINE_MODEL_NAME=model,
        TAVILY_API_KEY=settings.TAVILY_API_KEY,
        MAX_REFLECTIONS=2, SEARCH_CONTENT_MAX_LENGTH=20000,
        OUTPUT_DIR=OUTPUT_DIRS['query'],
    )
    llm_client = LLMClient(
        api_key=config.QUERY_ENGINE_API_KEY,
        model_name=config.QUERY_ENGINE_MODEL_NAME,
        base_url=config.QUERY_ENGINE_BASE_URL,
    )
    search_agency = TavilyNewsAgency(api_key=config.TAVILY_API_KEY)

    def progress_callback(data):
        publish(EventType.ENGINE_PROGRESS, {"engine": "query", **data})

    return run_research(query, config, llm_client, search_agency, progress_callback)


def _extract_citations_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract search history from run_research() result dict."""
    citations: List[Dict[str, Any]] = []
    paragraphs = result.get("paragraphs", [])
    for p_idx, p_dict in enumerate(paragraphs):
        research = p_dict.get("research", {}) if isinstance(p_dict, dict) else {}
        search_history = research.get("search_history", [])
        for search in search_history:
            citations.append({
                "paragraph_index": p_idx,
                "paragraph_title": p_dict.get("title", "") if isinstance(p_dict, dict) else "",
                "query": search.get("query", ""),
                "url": search.get("url"),
                "title": search.get("title"),
                "content": (search.get("content", "") or "")[:500],
                "score": search.get("score"),
                "search_count": len(search_history),
                "reflection_count": research.get("reflection_iteration", 0),
            })
    return citations
