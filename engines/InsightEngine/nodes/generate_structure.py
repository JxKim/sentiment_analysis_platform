"""
LangGraph node: generate report structure from query.
"""

import json
from copy import deepcopy

from loguru import logger

from ..state import InsightGraphState
from ..prompts import SYSTEM_PROMPT_REPORT_STRUCTURE
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_json_tags,
    extract_clean_response,
    fix_incomplete_json,
)
from ..context import InsightContext


class GenerateStructureNode:
    """Generate the report structure (paragraph list) from the user's query."""

    def __init__(self, ctx):
        self.ctx:InsightContext = ctx

    def __call__(self, state: InsightGraphState) -> dict:
        query = state["query"]
        self.ctx.progress_callback({"status": "structure", "message": "正在生成报告结构...", "progress_pct": 10})
        logger.info(f"\n{'=' * 60}\n[LangGraph] 生成报告结构: {query}")

        # TODO：这里一定要修复掉，完全没有必要使用
        raw = self.ctx.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_REPORT_STRUCTURE, query)
        structure = self._parse_structure(raw)

        paragraphs = []
        for p in structure:
            paragraphs.append({
                "title": p["title"],
                "content": p["content"],
                "research": {
                    "search_history": [],
                    "latest_summary": "",
                    "is_completed": False,
                    "reflection_iteration": 0,
                },
            })

        msg = f"报告结构已生成，共 {len(paragraphs)} 个段落:"
        for i, p in enumerate(paragraphs, 1):
            msg += f"\n  {i}. {p['title']}"
        logger.info(msg)

        return {
            "report_title": f"关于'{query}'的深度研究报告",
            "paragraphs": paragraphs,
            "current_paragraph_index": 0,
            "current_reflection_count": 0,
        }

    # ── Private helpers ──────────────────────────────────────────────

    def _parse_structure(self, output: str) -> list:
        cleaned = remove_reasoning_from_output(output)
        cleaned = clean_json_tags(cleaned)
        logger.info(f"清理后的输出: {cleaned}")

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            result = extract_clean_response(cleaned)
            if isinstance(result, dict) and "error" in result:
                fixed = fix_incomplete_json(cleaned)
                if fixed:
                    try:
                        result = json.loads(fixed)
                    except json.JSONDecodeError:
                        return self._default_structure()
                else:
                    return self._default_structure()

        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list):
            return self._default_structure()

        validated = []
        for item in result:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            content = item.get("content", "")
            if title and content:
                validated.append({"title": title, "content": content})

        return validated if validated else self._default_structure()

    @staticmethod
    def _default_structure() -> list:
        return [
            {"title": "研究概述", "content": "对查询主题进行总体概述和分析"},
            {"title": "深度分析", "content": "深入分析查询主题的各个方面"},
        ]
