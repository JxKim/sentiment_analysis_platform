"""
LangGraph node: generate report structure from query.
"""

import json

from loguru import logger

from ..state import InsightGraphState
from ..prompts import SYSTEM_PROMPT_REPORT_STRUCTURE
from ..context import InsightContext


class GenerateStructureNode:
    """Generate the report structure (paragraph list) from the user's query."""

    def __init__(self, ctx):
        self.ctx: InsightContext = ctx

    def __call__(self, state: InsightGraphState) -> dict:
        query = state["query"]
        self.ctx.progress_callback({"status": "structure", "message": "正在生成报告结构...", "progress_pct": 10})
        logger.info(f"\n{'=' * 60}\n[LangGraph] 生成报告结构: {query}")
        raw = self.ctx.llm_client.invoke(SYSTEM_PROMPT_REPORT_STRUCTURE, query, json_output=True)
        try:
            structure = json.loads(raw)
            if isinstance(structure, dict):
                structure = [structure]
        except json.JSONDecodeError:
            logger.error(f"生成JSON有误：{raw}")
            structure = self._default_structure()

        if not isinstance(structure, list):
            structure = self._default_structure()

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

    @staticmethod
    def _default_structure() -> list:
        return [
            {"title": "研究概述", "content": "对查询主题进行总体概述和分析"},
            {"title": "深度分析", "content": "深入分析查询主题的各个方面"},
        ]
