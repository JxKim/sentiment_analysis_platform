"""LangGraph node: reflection summary."""

import json
from copy import deepcopy
from loguru import logger

from app.services.event_bus import publish
from ..state import QueryGraphState
from ..prompts import SYSTEM_PROMPT_REFLECTION_SUMMARY
from ..utils.text_processing import remove_reasoning_from_output, clean_json_tags, fix_incomplete_json, format_search_results_for_prompt


class ReflectionSummaryNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, state: QueryGraphState) -> dict:
        idx = state["current_paragraph_index"]
        para = state["paragraphs"][idx]
        research = para.get("research", {})
        cs = research.get("current_search", {})
        count = state.get("current_reflection_count", 0)
        max_ref = state.get("max_reflections", 2)
        raw = self.ctx.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_REFLECTION_SUMMARY, json.dumps({"title": para["title"], "content": para["content"], "search_query": cs.get("query", ""), "search_results": format_search_results_for_prompt(cs.get("results", []), self.ctx.config.SEARCH_CONTENT_MAX_LENGTH), "paragraph_latest_state": research.get("latest_summary", "")}, ensure_ascii=False))
        updated = deepcopy(state["paragraphs"])
        updated[idx]["research"]["latest_summary"] = self._parse_summary(raw)
        updated[idx]["research"]["reflection_iteration"] = count + 1
        new_count = count + 1
        logger.info(f"    反思 {new_count} 完成")
        result = {"paragraphs": updated, "current_reflection_count": new_count}
        if new_count >= max_ref:
            updated[idx]["research"]["is_completed"] = True
            total = len(updated)
            pct = int(20 + (idx + 1) / total * 60)
            self._pc({"status": "processing", "message": f"段落 {idx+1}/{total} 完成", "progress_pct": pct, "paragraph_current": idx + 1, "paragraph_total": total})
            result["current_paragraph_index"] = idx + 1
        return result

    def _pc(self, data):
        if self.ctx.progress_callback:
            self.ctx.progress_callback(data)

    def _parse_summary(self, output: str) -> str:
        cleaned = remove_reasoning_from_output(output)
        cleaned = clean_json_tags(cleaned)
        logger.info(f"  清理后的输出: {cleaned}")
        # LLM may return actual newlines in JSON string values — escape them
        cleaned = cleaned.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')

        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                summary = result.get("updated_paragraph_latest_state", cleaned)
                publish("summary_ready", {"source": self.ctx.engine_name, "summary": summary, "type": "reflection"})
                return summary
        except json.JSONDecodeError:
            fixed = fix_incomplete_json(cleaned)
            if fixed:
                try:
                    result = json.loads(fixed)
                    if isinstance(result, dict):
                        summary = result.get("updated_paragraph_latest_state", cleaned)
                        publish("summary_ready", {"source": self.ctx.engine_name, "summary": summary, "type": "reflection"})
                        return summary
                except json.JSONDecodeError:
                    pass
        publish("summary_ready", {"source": self.ctx.engine_name, "summary": cleaned, "type": "reflection"})
        return cleaned
