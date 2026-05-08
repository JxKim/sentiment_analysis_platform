"""
Search service — runs Insight/Media/Query engine agents in background threads.
Publishes progress/results via event_bus SSE.
"""

import threading
from typing import Any, Dict, List

from loguru import logger

from app.services.event_bus import publish


OUTPUT_DIRS = {
    'insight': 'insight_engine_streamlit_reports',
    'media': 'media_engine_streamlit_reports',
    'query': 'query_engine_streamlit_reports',
}


def search_all(query: str):
    """Launch all 3 engine tasks in parallel background threads."""
    if not query.strip():
        return {"success": False, "message": "搜索查询不能为空"}

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
    try:
        publish("engine_progress", {
            "engine": engine_type,
            "status": "starting",
            "message": "正在初始化Agent...",
            "progress_pct": 0,
        })

        agent, _config = _create_agent(engine_type)

        # 将 LangGraph 各节点的进度事件转发为 SSE
        agent.progress_callback = lambda data: publish("engine_progress", {"engine": engine_type, **data})

        publish("engine_progress", {
            "engine": engine_type,
            "status": "starting",
            "message": "Agent就绪，开始研究...",
            "progress_pct": 5,
        })

        final_report = agent.research(query)

        publish("engine_progress", {
            "engine": engine_type,
            "status": "finalizing",
            "message": "研究完成",
            "progress_pct": 100,
        })

        publish("engine_result", {
            "engine": engine_type,
            "final_report": final_report,
            "citations": _extract_citations(agent),
        })

    except Exception as exc:
        import traceback
        logger.exception(f"{engine_type} engine error: {exc}")
        publish("engine_error", {
            "engine": engine_type,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })


def _create_agent(engine_type: str):
    """Instantiate the correct agent class and config for the given engine type."""
    import sys
    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent.parent
    for _p in [str(_root / "engines"), str(_root / "app" / "utils")]:
        if _p not in sys.path:
            sys.path.insert(0, _p)

    from app.config import settings, Settings

    if engine_type == 'insight':
        from InsightEngine import DeepSearchAgent
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
        return DeepSearchAgent(config), config

    if engine_type == 'media':
        from MediaEngine import DeepSearchAgent, TavilySearchAgent, AnspireSearchAgent
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

        if search_type == "TavilyAPI":
            agent = TavilySearchAgent(config)
        elif search_type == "BochaAPI":
            agent = DeepSearchAgent(config)
        elif search_type == "AnspireAPI":
            agent = AnspireSearchAgent(config)
        else:
            agent = DeepSearchAgent(config)
        return agent, config

    if engine_type == 'query':
        from QueryEngine import DeepSearchAgent
        model = settings.QUERY_ENGINE_MODEL_NAME or "deepseek-chat"
        config = Settings(
            QUERY_ENGINE_API_KEY=settings.QUERY_ENGINE_API_KEY,
            QUERY_ENGINE_BASE_URL=settings.QUERY_ENGINE_BASE_URL,
            QUERY_ENGINE_MODEL_NAME=model,
            TAVILY_API_KEY=settings.TAVILY_API_KEY,
            MAX_REFLECTIONS=2, SEARCH_CONTENT_MAX_LENGTH=20000,
            OUTPUT_DIR=OUTPUT_DIRS['query'],
        )
        return DeepSearchAgent(config), config

    raise ValueError(f"Unknown engine type: {engine_type}")


def _extract_citations(agent) -> List[Dict[str, Any]]:
    """Extract search history from agent state for frontend display."""
    citations: List[Dict[str, Any]] = []
    for p_idx, paragraph in enumerate(agent.state.paragraphs):
        for search in paragraph.research.search_history:
            citations.append({
                "paragraph_index": p_idx,
                "paragraph_title": paragraph.title,
                "query": getattr(search, 'query', ''),
                "url": getattr(search, 'url', None),
                "title": getattr(search, 'title', None),
                "content": (getattr(search, 'content', '') or '')[:500],
                "score": getattr(search, 'score', None),
                "search_count": paragraph.research.get_search_count(),
                "reflection_count": paragraph.research.reflection_iteration,
            })
    return citations
