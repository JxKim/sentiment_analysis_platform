"""LangGraph node: initial summary."""

import json
from copy import deepcopy
from loguru import logger

from app.services.event_bus import publish
from app.services.event_types import EventType
from ..state import QueryGraphState
from ..prompts import SYSTEM_PROMPT_FIRST_SUMMARY
from ..utils.text_processing import remove_reasoning_from_output, clean_json_tags, fix_incomplete_json, format_search_results_for_prompt

import sys as _sys
import os as _os
_sys.path.append(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))))
try:
    from utils.forum_reader import get_latest_host_speech, format_host_speech_for_prompt
    _FORUM_AVAILABLE = True
except ImportError:
    _FORUM_AVAILABLE = False


class InitialSummaryNode:
    def __init__(self, ctx):
        self.ctx = ctx

    def __call__(self, state: QueryGraphState) -> dict:
        idx = state["current_paragraph_index"]
        para = state["paragraphs"][idx]
        cs = para.get("research", {}).get("current_search", {})
        logger.info("  - 生成初始总结...")
        payload = {"title": para["title"], "content": para["content"], "search_query": cs.get("query", ""), "search_results": format_search_results_for_prompt(cs.get("results", []), self.ctx.config.SEARCH_CONTENT_MAX_LENGTH)}
        if _FORUM_AVAILABLE:
            try:
                host_speech = get_latest_host_speech()
                if host_speech:
                    payload["host_speech"] = host_speech
                    logger.info(f"  已读取HOST发言，长度: {len(host_speech)}字符")
            except Exception as e:
                logger.exception(f"  读取HOST发言失败: {e}")
        message = json.dumps(payload, ensure_ascii=False)
        if _FORUM_AVAILABLE and "host_speech" in payload:
            message = format_host_speech_for_prompt(payload["host_speech"]) + "\n" + message
        raw = self.ctx.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_FIRST_SUMMARY, message)
        updated = deepcopy(state["paragraphs"])
        updated[idx]["research"]["latest_summary"] = self._parse_summary(raw)
        logger.info("  - 初始总结完成")
        return {"paragraphs": updated, "current_reflection_count": 0}

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
