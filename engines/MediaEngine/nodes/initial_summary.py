"""
LangGraph node: initial summary — generate paragraph summary from search results.
"""

import json
from copy import deepcopy

from loguru import logger

from app.services.event_bus import publish

from ..state import MediaGraphState
from ..prompts import SYSTEM_PROMPT_FIRST_SUMMARY
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_json_tags,
    fix_incomplete_json,
    format_search_results_for_prompt,
)


class InitialSummaryNode:
    """Generate initial summary for the current paragraph based on search results."""

    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, state: MediaGraphState) -> dict:
        idx = state["current_paragraph_index"]
        para = state["paragraphs"][idx]
        research = para.get("research", {})
        current_search = research.get("current_search", {})

        search_query = current_search.get("query", "")
        search_results = current_search.get("results", [])
        logger.info("  - 生成初始总结...")

        summary_input = {
            "title": para["title"],
            "content": para["content"],
            "search_query": search_query,
            "search_results": format_search_results_for_prompt(
                search_results, self.ctx.config.SEARCH_CONTENT_MAX_LENGTH,
            ),
        }
        message = json.dumps(summary_input, ensure_ascii=False)
        raw = self.ctx.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_FIRST_SUMMARY, message)
        summary_text = self._parse_summary(raw)

        updated = deepcopy(state["paragraphs"])
        updated[idx]["research"]["latest_summary"] = summary_text
        logger.info("  - 初始总结完成")
        return {"paragraphs": updated, "current_reflection_count": 0}

    def _parse_summary(self, output: str) -> str:
        cleaned = remove_reasoning_from_output(output)
        cleaned = clean_json_tags(cleaned)
        logger.info(f"  清理后的输出: {cleaned}")
        publish("summary_ready", {"source": self.ctx.engine_name, "summary": cleaned, "type": "initial"})
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result.get("paragraph_latest_state", cleaned)
        except json.JSONDecodeError:
            fixed = fix_incomplete_json(cleaned)
            if fixed:
                try:
                    result = json.loads(fixed)
                    if isinstance(result, dict):
                        return result.get("paragraph_latest_state", cleaned)
                except json.JSONDecodeError:
                    pass
        return cleaned
