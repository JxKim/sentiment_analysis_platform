"""
LangGraph node: initial summary — generate paragraph summary from search results.
"""

import json
from copy import deepcopy

from loguru import logger

from app.services.event_bus import publish
from app.services.event_types import EventType
from app.utils.forum_reader import get_latest_host_speech,format_host_speech_for_prompt
from ..state import InsightGraphState
from ..prompts import SYSTEM_PROMPT_FIRST_SUMMARY
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_json_tags,
    fix_incomplete_json,
)
from ..utils import format_search_results_for_prompt
from ..context import InsightContext



class InitialSummaryNode:
    """Generate initial summary for the current paragraph based on search results."""

    def __init__(self, ctx):
        self.ctx:InsightContext = ctx

    def __call__(self, state: InsightGraphState) -> dict:
        idx = state["current_paragraph_index"]
        para = state["paragraphs"][idx]
        research = para.get("research", {})
        current_search = research.get("current_search", {})

        search_query = current_search.get("query", "")
        search_results = current_search.get("results", [])
        logger.info("  - 生成初始总结...")

        # Build prompt input
        summary_input = {
            "title": para["title"],
            "content": para["content"],
            "search_query": search_query,
            "search_results": format_search_results_for_prompt(
                search_results, self.ctx.config.MAX_CONTENT_LENGTH,
            ),
        }

        # Attach HOST speech if available
        
        try:
            host_speech = get_latest_host_speech()
            if host_speech:
                summary_input["host_speech"] = host_speech
                logger.info(f"  已读取HOST发言，长度: {len(host_speech)}字符")
        except Exception as e:
            logger.exception(f"  读取HOST发言失败: {e}")

        message = json.dumps(summary_input, ensure_ascii=False)
        if "host_speech" in summary_input:
            message = format_host_speech_for_prompt(summary_input["host_speech"]) + "\n" + message

        raw = self.ctx.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_FIRST_SUMMARY, message)
        summary_text = self._parse_summary(raw)

        updated = deepcopy(state["paragraphs"])
        updated[idx]["research"]["latest_summary"] = summary_text
        logger.info("  - 初始总结完成")
        return {"paragraphs": updated, "current_reflection_count": 0}

    # ── Private helpers ──────────────────────────────────────────────
    
    def _parse_summary(self, output: str) -> str:
        cleaned = remove_reasoning_from_output(output)
        cleaned = clean_json_tags(cleaned)
        logger.info(f"  清理后的输出: {cleaned}")
        cleaned = cleaned.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')
        summary = self._extract_summary(cleaned, ("paragraph_latest_state", "updated_paragraph_latest_state", "content", "summary"))
        if summary is not None:
            publish(EventType.SUMMARY_READY, {"source": self.ctx.engine_name, "summary": summary, "type": "initial"})
            return summary
        publish(EventType.SUMMARY_READY, {"source": self.ctx.engine_name, "summary": cleaned, "type": "initial"})
        return cleaned

    @staticmethod
    def _extract_summary(cleaned: str, keys: tuple) -> str | None:
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                for key in keys:
                    val = result.get(key)
                    if isinstance(val, str) and val.strip():
                        return val
        except json.JSONDecodeError:
            pass
        from ..utils.text_processing import fix_incomplete_json
        fixed = fix_incomplete_json(cleaned)
        if fixed:
            try:
                result = json.loads(fixed)
                if isinstance(result, dict):
                    for key in keys:
                        val = result.get(key)
                        if isinstance(val, str) and val.strip():
                            return val
            except json.JSONDecodeError:
                pass
        return None