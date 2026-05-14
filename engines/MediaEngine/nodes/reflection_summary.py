"""
LangGraph node: reflection summary — update paragraph summary with new search data.
"""

import json
from copy import deepcopy

from loguru import logger

from app.services.event_bus import publish
from app.services.event_types import EventType

from ..state import MediaGraphState
from ..prompts import SYSTEM_PROMPT_REFLECTION_SUMMARY
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_json_tags,
    fix_incomplete_json,
    format_search_results_for_prompt,
)

import sys as _sys
import os as _os
_sys.path.append(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))))
try:
    from utils.forum_reader import get_latest_host_speech, format_host_speech_for_prompt
    _FORUM_AVAILABLE = True
except ImportError:
    _FORUM_AVAILABLE = False


class ReflectionSummaryNode:
    """Update the current paragraph's summary with reflection search results."""

    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, state: MediaGraphState) -> dict:
        idx = state["current_paragraph_index"]
        para = state["paragraphs"][idx]
        research = para.get("research", {})
        current_search = research.get("current_search", {})
        count = state.get("current_reflection_count", 0)
        max_ref = state.get("max_reflections", 2)

        search_query = current_search.get("query", "")
        search_results = current_search.get("results", [])

        summary_input = {
            "title": para["title"],
            "content": para["content"],
            "search_query": search_query,
            "search_results": format_search_results_for_prompt(
                search_results, self.ctx.config.SEARCH_CONTENT_MAX_LENGTH,
            ),
            "paragraph_latest_state": research.get("latest_summary", ""),
        }
        if _FORUM_AVAILABLE:
            try:
                host_speech = get_latest_host_speech()
                if host_speech:
                    summary_input["host_speech"] = host_speech
            except Exception:
                pass
        message = json.dumps(summary_input, ensure_ascii=False)
        if _FORUM_AVAILABLE and "host_speech" in summary_input:
            message = format_host_speech_for_prompt(summary_input["host_speech"]) + "\n" + message
        raw = self.ctx.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_REFLECTION_SUMMARY, message)
        summary_text = self._parse_summary(raw)

        updated = deepcopy(state["paragraphs"])
        updated[idx]["research"]["latest_summary"] = summary_text
        updated[idx]["research"]["reflection_iteration"] = count + 1
        new_count = count + 1
        logger.info(f"    反思 {new_count} 完成")

        result: dict = {"paragraphs": updated, "current_reflection_count": new_count}
        if new_count >= max_ref:
            updated[idx]["research"]["is_completed"] = True
            total = len(updated)
            pct = int(20 + (idx + 1) / total * 60)
            self._pc({
                "status": "processing",
                "message": f"段落 {idx+1}/{total} 完成",
                "progress_pct": pct,
                "paragraph_current": idx + 1,
                "paragraph_total": total,
            })
            result["current_paragraph_index"] = idx + 1

        return result

    def _pc(self, data: dict):
        if self.ctx.progress_callback:
            self.ctx.progress_callback(data)

    def _parse_summary(self, output: str) -> str:
        cleaned = remove_reasoning_from_output(output)
        cleaned = clean_json_tags(cleaned)
        logger.info(f"  清理后的输出: {cleaned}")
        cleaned = cleaned.replace('\r\n', '\\n').replace('\r', '\\n').replace('\n', '\\n')
        summary = self._extract_summary(cleaned, ("paragraph_latest_state", "updated_paragraph_latest_state", "content", "summary"))
        if summary is not None:
            publish(EventType.SUMMARY_READY, {"source": self.ctx.engine_name, "summary": summary, "type": "reflection"})
            return summary
        publish(EventType.SUMMARY_READY, {"source": self.ctx.engine_name, "summary": cleaned, "type": "reflection"})
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