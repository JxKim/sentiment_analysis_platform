"""
InsightContext — clean dependency container for InsightEngine graph.

Holds config, LLM client, search tools, and utility methods.
LangGraph node classes receive ctx and pull what they need.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
from loguru import logger
from sklearn.cluster import KMeans

from .llms import LLMClient
from .tools import (
    DBResponse,
    MediaCrawlerDB,
    get_keyword_optimizer,
    multilingual_sentiment_analyzer,
)
from .utils.config import Settings

ENABLE_CLUSTERING: bool = True
MAX_CLUSTERED_RESULTS: int = 50
RESULTS_PER_CLUSTER: int = 5


@dataclass
class InsightContext:
    """Holds all dependencies needed by InsightEngine's LangGraph nodes."""

    llm_client: LLMClient
    config: Settings
    engine_name: str = "insight"
    search_agency: MediaCrawlerDB = field(default_factory=MediaCrawlerDB)
    progress_callback: Optional[Callable] = None

    # Lazy-loaded helpers
    _clustering_model: Any = None
    sentiment_analyzer: Any = None

    def __post_init__(self):
        if self.sentiment_analyzer is None:
            self.sentiment_analyzer = multilingual_sentiment_analyzer

    # ── Search execution ──────────────────────────────────────────────

    def execute_search(self, tool_name: str, query: str, **kwargs) -> DBResponse:
        """
        Execute a database query tool with keyword optimization and sentiment analysis.
        (Moved from DeepSearchAgent.execute_search_tool)
        """
        logger.info(f"  → 执行数据库查询工具: {tool_name}")

        if tool_name == "search_hot_content":
            time_period = kwargs.get("time_period", "week")
            limit = kwargs.get("limit", 100)
            response = self.search_agency.search_hot_content(
                time_period=time_period, limit=limit
            )
            enable_sentiment = kwargs.get("enable_sentiment", True)
            if enable_sentiment and response.results:
                logger.info("  🎭 开始对热点内容进行情感分析...")
                analysis = self._perform_sentiment_analysis(response.results)
                if analysis:
                    response.parameters["sentiment_analysis"] = analysis
            return response

        if tool_name == "analyze_sentiment":
            texts = kwargs.get("texts", query)
            result = self.analyze_sentiment_only(texts)
            return DBResponse(
                tool_name="analyze_sentiment",
                parameters={"texts": texts if isinstance(texts, list) else [texts], **kwargs},
                results=[], results_count=0,
                metadata=result,
            )

        # Keyword-optimized search
        optimized = get_keyword_optimizer().optimize_keywords(
            original_query=query, context=f"使用{tool_name}工具进行查询"
        )
        logger.info(f"  🔍 原始查询: '{query}'")
        logger.info(f"  ✨ 优化后关键词: {optimized.optimized_keywords}")

        all_results = []
        total_count = 0
        for keyword in optimized.optimized_keywords:
            logger.info(f"    查询关键词: '{keyword}'")
            try:
                response = self._dispatch_search(tool_name, keyword, **kwargs)
                if response and response.results:
                    logger.info(f"     找到 {len(response.results)} 条结果")
                    all_results.extend(response.results)
                    total_count += len(response.results)
            except Exception as e:
                logger.error(f"     查询 '{keyword}' 时出错: {str(e)}")

        unique_results = self._deduplicate_results(all_results)
        logger.info(f"  总计 {total_count} 条，去重后 {len(unique_results)} 条")

        if ENABLE_CLUSTERING:
            unique_results = self._cluster_and_sample_results(unique_results)

        response = DBResponse(
            tool_name=f"{tool_name}_optimized",
            parameters={
                "original_query": query,
                "optimized_keywords": optimized.optimized_keywords,
                "optimization_reasoning": optimized.reasoning,
                **kwargs,
            },
            results=unique_results,
            results_count=len(unique_results),
        )

        enable_sentiment = kwargs.get("enable_sentiment", True)
        if enable_sentiment and unique_results:
            logger.info("  🎭 开始对搜索结果进行情感分析...")
            analysis = self._perform_sentiment_analysis(unique_results)
            if analysis:
                response.parameters["sentiment_analysis"] = analysis

        return response

    def _dispatch_search(self, tool_name: str, keyword: str, **kwargs) -> Optional[DBResponse]:
        """Route to the right MediaCrawlerDB method based on tool_name."""
        if tool_name == "search_topic_globally":
            limit = self.config.DEFAULT_SEARCH_TOPIC_GLOBALLY_LIMIT_PER_TABLE
            return self.search_agency.search_topic_globally(topic=keyword, limit_per_table=limit)
        if tool_name == "search_topic_by_date":
            start = kwargs.get("start_date")
            end = kwargs.get("end_date")
            if not start or not end:
                raise ValueError("search_topic_by_date needs start_date and end_date")
            limit = self.config.DEFAULT_SEARCH_TOPIC_BY_DATE_LIMIT_PER_TABLE
            return self.search_agency.search_topic_by_date(topic=keyword, start_date=start, end_date=end, limit_per_table=limit)
        if tool_name == "get_comments_for_topic":
            limit = max(self.config.DEFAULT_GET_COMMENTS_FOR_TOPIC_LIMIT // 3, 50)
            return self.search_agency.get_comments_for_topic(topic=keyword, limit=limit)
        if tool_name == "search_topic_on_platform":
            platform = kwargs.get("platform")
            start = kwargs.get("start_date")
            end = kwargs.get("end_date")
            if not platform:
                raise ValueError("search_topic_on_platform needs platform")
            limit = max(self.config.DEFAULT_SEARCH_TOPIC_ON_PLATFORM_LIMIT // 3, 30)
            return self.search_agency.search_topic_on_platform(platform=platform, topic=keyword, start_date=start, end_date=end, limit=limit)
        logger.warning(f"未知工具 '{tool_name}'，使用默认全局搜索")
        limit = self.config.DEFAULT_SEARCH_TOPIC_GLOBALLY_LIMIT_PER_TABLE
        return self.search_agency.search_topic_globally(topic=keyword, limit_per_table=limit)

    # ── Clustering ────────────────────────────────────────────────────

    def _get_clustering_model(self):
        if self._clustering_model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("  加载聚类模型 (paraphrase-multilingual-MiniLM-L12-v2)...")
            self._clustering_model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
        return self._clustering_model

    def _cluster_and_sample_results(self, results: list, max_results: int = MAX_CLUSTERED_RESULTS,
                                    results_per_cluster: int = RESULTS_PER_CLUSTER) -> list:
        if len(results) <= max_results:
            return results
        try:
            texts = [r.title_or_content[:500] for r in results]
            model = self._get_clustering_model()
            embeddings = model.encode(texts, show_progress_bar=False)
            n_clusters = min(max(2, max_results // results_per_cluster), len(results))
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(embeddings)

            sampled = []
            for cid in range(n_clusters):
                indices = np.flatnonzero(labels == cid)
                cluster = [(results[i], i) for i in indices]
                cluster.sort(key=lambda x: x[0].hotness_score or 0, reverse=True)
                for r, _ in cluster[:results_per_cluster]:
                    sampled.append(r)
                    if len(sampled) >= max_results:
                        break
                if len(sampled) >= max_results:
                    break
            logger.info(f"  聚类: {len(results)} 条 -> {n_clusters} 主题 -> {len(sampled)} 条")
            return sampled
        except Exception as e:
            logger.warning(f"  聚类失败: {e}")
            return results[:max_results]

    def _deduplicate_results(self, results: list) -> list:
        seen = set()
        unique = []
        for r in results:
            key = r.url if r.url else r.title_or_content[:100]
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    # ── Sentiment analysis ────────────────────────────────────────────

    def _perform_sentiment_analysis(self, results: list) -> Optional[Dict[str, Any]]:
        try:
            if not self.sentiment_analyzer.is_initialized and not self.sentiment_analyzer.is_disabled:
                logger.info("    初始化情感分析模型...")
                if not self.sentiment_analyzer.initialize():
                    logger.info("     情感分析模型初始化失败")
            results_dict = [{
                "content": r.title_or_content, "platform": r.platform,
                "author": r.author_nickname, "url": r.url,
                "publish_time": str(r.publish_time) if r.publish_time else None,
            } for r in results]
            sa = self.sentiment_analyzer.analyze_query_results(
                query_results=results_dict, text_field="content", min_confidence=0.5
            )
            return sa.get("sentiment_analysis")
        except Exception as e:
            logger.exception(f"情感分析出错: {e}")
            return None

    def analyze_sentiment_only(self, texts: Union[str, List[str]]) -> Dict[str, Any]:
        try:
            if not self.sentiment_analyzer.is_initialized and not self.sentiment_analyzer.is_disabled:
                logger.info("    初始化情感分析模型...")
                if not self.sentiment_analyzer.initialize():
                    logger.info("     情感分析模型初始化失败")
            if isinstance(texts, str):
                result = self.sentiment_analyzer.analyze_single_text(texts)
                return {"success": result.success and result.analysis_performed,
                        "total_analyzed": 1 if result.analysis_performed and result.success else 0,
                        "results": [result.__dict__]}
            batch = self.sentiment_analyzer.analyze_batch(list(texts), show_progress=True)
            return {"success": batch.analysis_performed and batch.success_count > 0,
                    "total_analyzed": batch.total_processed if batch.analysis_performed else 0,
                    "success_count": batch.success_count, "failed_count": batch.failed_count,
                    "average_confidence": batch.average_confidence if batch.analysis_performed else 0.0,
                    "results": [r.__dict__ for r in batch.results]}
        except Exception as e:
            logger.exception(f"情感分析出错: {e}")
            return {"success": False, "error": str(e), "results": []}

    # ── Utilities ─────────────────────────────────────────────────────

    @staticmethod
    def validate_date_format(date_str: str) -> bool:
        if not date_str:
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False
