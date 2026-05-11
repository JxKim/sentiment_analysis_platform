"""LangGraph node: initial summary."""

import json
from copy import deepcopy
from loguru import logger

from app.services.event_bus import publish
from ..state import QueryGraphState
from ..prompts import SYSTEM_PROMPT_FIRST_SUMMARY
from ..utils.text_processing import remove_reasoning_from_output, clean_json_tags, fix_incomplete_json, format_search_results_for_prompt


class InitialSummaryNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, state: QueryGraphState) -> dict:
        idx = state["current_paragraph_index"]
        para = state["paragraphs"][idx]
        cs = para.get("research", {}).get("current_search", {})
        logger.info("  - 生成初始总结...")
        raw = self.ctx.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_FIRST_SUMMARY, json.dumps({"title": para["title"], "content": para["content"], "search_query": cs.get("query", ""), "search_results": format_search_results_for_prompt(cs.get("results", []), self.ctx.config.SEARCH_CONTENT_MAX_LENGTH)}, ensure_ascii=False))
        updated = deepcopy(state["paragraphs"])
        updated[idx]["research"]["latest_summary"] = self._parse_summary(raw)
        logger.info("  - 初始总结完成")
        return {"paragraphs": updated, "current_reflection_count": 0}

    def _parse_summary(self, output: str) -> str:
        cleaned = remove_reasoning_from_output(output)
        cleaned = clean_json_tags(cleaned)
        logger.info(f"  清理后的输出: {cleaned}")
        # LLM may return actual newlines in JSON string values — escape them
        cleaned = cleaned.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')

        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                summary = result.get("paragraph_latest_state", cleaned)
                publish("summary_ready", {"source": self.ctx.engine_name, "summary": summary, "type": "initial"})
                return summary
        except json.JSONDecodeError:
            fixed = fix_incomplete_json(cleaned)
            if fixed:
                try:
                    result = json.loads(fixed)
                    if isinstance(result, dict):
                        summary = result.get("paragraph_latest_state", cleaned)
                        publish("summary_ready", {"source": self.ctx.engine_name, "summary": summary, "type": "initial"})
                        return summary
                except json.JSONDecodeError:
                    pass
        publish("summary_ready", {"source": self.ctx.engine_name, "summary": cleaned, "type": "initial"})
        return cleaned
