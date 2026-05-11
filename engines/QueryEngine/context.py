"""QueryContext — dependency container for QueryEngine graph."""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from loguru import logger

from .llms import LLMClient


@dataclass
class QueryContext:
    llm_client: LLMClient
    config: Any
    search_agency: Any
    engine_name: str = "query"
    progress_callback: Optional[Callable] = None

    def execute_search(self, tool_name: str, query: str, **kwargs) -> Any:
        logger.info(f"  → 执行搜索工具: {tool_name}")
        dispatch = {
            "basic_search_news": lambda: self.search_agency.basic_search_news(query, kwargs.get("max_results", 7)),
            "deep_search_news": lambda: self.search_agency.deep_search_news(query),
            "search_news_last_24_hours": lambda: self.search_agency.search_news_last_24_hours(query),
            "search_news_last_week": lambda: self.search_agency.search_news_last_week(query),
            "search_images_for_news": lambda: self.search_agency.search_images_for_news(query),
            "search_news_by_date": lambda: self.search_agency.search_news_by_date(
                query, kwargs["start_date"], kwargs["end_date"],
            ),
        }
        fn = dispatch.get(tool_name)
        if fn:
            return fn()
        logger.warning(f"未知搜索工具: {tool_name}，使用默认基础搜索")
        return self.search_agency.basic_search_news(query)

    @staticmethod
    def validate_date_format(date_str: str) -> bool:
        if not date_str:
            return False
        from datetime import datetime
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False
