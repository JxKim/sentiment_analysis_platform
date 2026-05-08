"""
Deep Search Agent主类
整合所有模块，实现完整的深度搜索流程
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans

from .llms import LLMClient
from .nodes import (
    FirstSearchNode,
    FirstSummaryNode,
    ReflectionNode,
    ReflectionSummaryNode,
    ReportFormattingNode,
)
from .state import Paragraph, State
from .tools import (
    DBResponse,
    MediaCrawlerDB,
    keyword_optimizer,
    get_keyword_optimizer,
    multilingual_sentiment_analyzer,
)
from .utils import format_search_results_for_prompt
from .utils.config import Settings, settings
from .graph import build_insight_graph

ENABLE_CLUSTERING: bool = True  # 是否启用聚类采样
MAX_CLUSTERED_RESULTS: int = 50  # 聚类后最大返回结果数
RESULTS_PER_CLUSTER: int = 5  # 每个聚类返回的结果数


class DeepSearchAgent:
    """Deep Search Agent主类"""

    def __init__(self, config: Optional[Settings] = None):
        """
        初始化Deep Search Agent

        Args:
            config: 可选配置对象（不填则用全局settings）
        """
        self.config = config or settings

        # 初始化LLM客户端
        self.llm_client = self._initialize_llm()

        # 初始化搜索工具集
        self.search_agency = MediaCrawlerDB()

        # 初始化聚类小模型（懒加载）
        self._clustering_model = None

        # 初始化情感分析器
        self.sentiment_analyzer = multilingual_sentiment_analyzer

        # 初始化节点
        self._initialize_nodes()

        # 状态
        self.state = State()

        # 进度回调（由调用方设置，供 graph.py LangGraph 节点适配器使用）
        self.progress_callback = None

        # 确保输出目录存在
        os.makedirs(self.config.OUTPUT_DIR, exist_ok=True)

        # 构建 LangGraph 图
        self.graph = build_insight_graph(self)

        logger.info(f"Insight Agent已初始化")
        logger.info(f"使用LLM: {self.llm_client.get_model_info()}")
        logger.info(f"搜索工具集: MediaCrawlerDB (支持5种本地数据库查询工具)")
        logger.info(f"情感分析: WeiboMultilingualSentiment (支持22种语言的情感分析)")

    def _initialize_llm(self) -> LLMClient:
        """初始化LLM客户端"""
        return LLMClient(
            api_key=self.config.INSIGHT_ENGINE_API_KEY,
            model_name=self.config.INSIGHT_ENGINE_MODEL_NAME,
            base_url=self.config.INSIGHT_ENGINE_BASE_URL,
        )

    def _initialize_nodes(self):
        """初始化处理节点"""
        self.first_search_node = FirstSearchNode(self.llm_client)
        self.reflection_node = ReflectionNode(self.llm_client)
        self.first_summary_node = FirstSummaryNode(self.llm_client)
        self.reflection_summary_node = ReflectionSummaryNode(self.llm_client)
        self.report_formatting_node = ReportFormattingNode(self.llm_client)

    def _get_clustering_model(self):
        """懒加载聚类模型"""
        if self._clustering_model is None:
            logger.info("  加载聚类模型 (paraphrase-multilingual-MiniLM-L12-v2)...")
            self._clustering_model = SentenceTransformer(
                "paraphrase-multilingual-MiniLM-L12-v2"
            )
        return self._clustering_model

    def _validate_date_format(self, date_str: str) -> bool:
        """
        验证日期格式是否为YYYY-MM-DD

        Args:
            date_str: 日期字符串

        Returns:
            是否为有效格式
        """
        if not date_str:
            return False

        # 检查格式
        pattern = r"^\d{4}-\d{2}-\d{2}$"
        if not re.match(pattern, date_str):
            return False

        # 检查日期是否有效
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    def _cluster_and_sample_results(
        self,
        results: List,
        max_results: int = MAX_CLUSTERED_RESULTS,
        results_per_cluster: int = RESULTS_PER_CLUSTER,
    ) -> List:
        """
        对搜索结果进行聚类并采样

        Args:
            results: 搜索结果列表
            max_results: 最大返回结果数
            results_per_cluster: 每个聚类返回的结果数

        Returns:
            采样后的结果列表
        """
        if len(results) <= max_results:
            return results

        try:
            # 提取文本
            texts = [r.title_or_content[:500] for r in results]

            # 获取模型并编码
            model = self._get_clustering_model()
            embeddings = model.encode(texts, show_progress_bar=False)

            # 计算聚类数
            n_clusters = min(max(2, max_results // results_per_cluster), len(results))

            # KMeans聚类
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(embeddings)

            # 从每个聚类采样
            sampled_results = []
            for cluster_id in range(n_clusters):
                cluster_indices = np.flatnonzero(labels == cluster_id)
                cluster_results = [(results[i], i) for i in cluster_indices]
                cluster_results.sort(
                    key=lambda x: x[0].hotness_score or 0, reverse=True
                )

                for result, _ in cluster_results[:results_per_cluster]:
                    sampled_results.append(result)
                    if len(sampled_results) >= max_results:
                        break

                if len(sampled_results) >= max_results:
                    break

            logger.info(
                f"  聚类完成: {len(results)} 条 -> {n_clusters} 个主题 -> {len(sampled_results)} 条代表性结果"
            )
            return sampled_results

        except Exception as e:
            logger.warning(f"  聚类失败，返回前{max_results}条: {str(e)}")
            return results[:max_results]

    def execute_search_tool(self, tool_name: str, query: str, **kwargs) -> DBResponse:
        """
        执行指定的数据库查询工具（集成关键词优化中间件和情感分析）

        Args:
            tool_name: 工具名称，可选值：
                - "search_hot_content": 查找热点内容
                - "search_topic_globally": 全局话题搜索
                - "search_topic_by_date": 按日期搜索话题
                - "get_comments_for_topic": 获取话题评论
                - "search_topic_on_platform": 平台定向搜索
                - "analyze_sentiment": 对查询结果进行情感分析
            query: 搜索关键词/话题
            **kwargs: 额外参数（如start_date, end_date, platform, limit, enable_sentiment等）
                     enable_sentiment: 是否自动对搜索结果进行情感分析（默认True）

        Returns:
            DBResponse对象（可能包含情感分析结果）
        """
        logger.info(f"  → 执行数据库查询工具: {tool_name}")

        # 对于热点内容搜索，不需要关键词优化（因为不需要query参数）
        if tool_name == "search_hot_content":
            time_period = kwargs.get("time_period", "week")
            limit = kwargs.get("limit", 100)
            response = self.search_agency.search_hot_content(
                time_period=time_period, limit=limit
            )

            # 检查是否需要进行情感分析
            enable_sentiment = kwargs.get("enable_sentiment", True)
            if enable_sentiment and response.results and len(response.results) > 0:
                logger.info(f"  🎭 开始对热点内容进行情感分析...")
                sentiment_analysis = self._perform_sentiment_analysis(response.results)
                if sentiment_analysis:
                    # 将情感分析结果添加到响应的parameters中
                    response.parameters["sentiment_analysis"] = sentiment_analysis
                    logger.info(f"  ✅ 情感分析完成")

            return response

        # 独立情感分析工具
        if tool_name == "analyze_sentiment":
            texts = kwargs.get("texts", query)  # 可以通过texts参数传递，或使用query
            sentiment_result = self.analyze_sentiment_only(texts)

            # 构建DBResponse格式的响应
            return DBResponse(
                tool_name="analyze_sentiment",
                parameters={
                    "texts": texts if isinstance(texts, list) else [texts],
                    **kwargs,
                },
                results=[],  # 情感分析不返回搜索结果
                results_count=0,
                metadata=sentiment_result,
            )

        # 对于需要搜索词的工具，使用关键词优化中间件
        optimized_response = get_keyword_optimizer().optimize_keywords(
            original_query=query, context=f"使用{tool_name}工具进行查询"
        )

        logger.info(f"  🔍 原始查询: '{query}'")
        logger.info(f"  ✨ 优化后关键词: {optimized_response.optimized_keywords}")

        # 使用优化后的关键词进行多次查询并整合结果
        all_results = []
        total_count = 0

        for keyword in optimized_response.optimized_keywords:
            logger.info(f"    查询关键词: '{keyword}'")

            try:
                if tool_name == "search_topic_globally":
                    # 使用配置文件中的默认值，忽略agent提供的limit_per_table参数
                    limit_per_table = (
                        self.config.DEFAULT_SEARCH_TOPIC_GLOBALLY_LIMIT_PER_TABLE
                    )
                    response = self.search_agency.search_topic_globally(
                        topic=keyword, limit_per_table=limit_per_table
                    )
                elif tool_name == "search_topic_by_date":
                    start_date = kwargs.get("start_date")
                    end_date = kwargs.get("end_date")
                    # 使用配置文件中的默认值，忽略agent提供的limit_per_table参数
                    limit_per_table = (
                        self.config.DEFAULT_SEARCH_TOPIC_BY_DATE_LIMIT_PER_TABLE
                    )
                    if not start_date or not end_date:
                        raise ValueError(
                            "search_topic_by_date工具需要start_date和end_date参数"
                        )
                    response = self.search_agency.search_topic_by_date(
                        topic=keyword,
                        start_date=start_date,
                        end_date=end_date,
                        limit_per_table=limit_per_table,
                    )
                elif tool_name == "get_comments_for_topic":
                    # 使用配置文件中的默认值，按关键词数量分配，但保证最小值
                    limit = self.config.DEFAULT_GET_COMMENTS_FOR_TOPIC_LIMIT // len(
                        optimized_response.optimized_keywords
                    )
                    limit = max(limit, 50)
                    response = self.search_agency.get_comments_for_topic(
                        topic=keyword, limit=limit
                    )
                elif tool_name == "search_topic_on_platform":
                    platform = kwargs.get("platform")
                    start_date = kwargs.get("start_date")
                    end_date = kwargs.get("end_date")
                    # 使用配置文件中的默认值，按关键词数量分配，但保证最小值
                    limit = self.config.DEFAULT_SEARCH_TOPIC_ON_PLATFORM_LIMIT // len(
                        optimized_response.optimized_keywords
                    )
                    limit = max(limit, 30)
                    if not platform:
                        raise ValueError("search_topic_on_platform工具需要platform参数")
                    response = self.search_agency.search_topic_on_platform(
                        platform=platform,
                        topic=keyword,
                        start_date=start_date,
                        end_date=end_date,
                        limit=limit,
                    )
                else:
                    logger.info(f"    未知的搜索工具: {tool_name}，使用默认全局搜索")
                    response = self.search_agency.search_topic_globally(
                        topic=keyword,
                        limit_per_table=self.config.DEFAULT_SEARCH_TOPIC_GLOBALLY_LIMIT_PER_TABLE,
                    )

                # 收集结果
                if response.results:
                    logger.info(f"     找到 {len(response.results)} 条结果")
                    all_results.extend(response.results)
                    total_count += len(response.results)
                else:
                    logger.info(f"     未找到结果")

            except Exception as e:
                logger.error(f"      查询'{keyword}'时出错: {str(e)}")
                continue

        # 去重和整合结果
        unique_results = self._deduplicate_results(all_results)
        logger.info(f"  总计找到 {total_count} 条结果，去重后 {len(unique_results)} 条")

        if ENABLE_CLUSTERING:
            unique_results = self._cluster_and_sample_results(
                unique_results,
                max_results=MAX_CLUSTERED_RESULTS,
                results_per_cluster=RESULTS_PER_CLUSTER,
            )

        # 构建整合后的响应
        integrated_response = DBResponse(
            tool_name=f"{tool_name}_optimized",
            parameters={
                "original_query": query,
                "optimized_keywords": optimized_response.optimized_keywords,
                "optimization_reasoning": optimized_response.reasoning,
                **kwargs,
            },
            results=unique_results,
            results_count=len(unique_results),
        )

        # 检查是否需要进行情感分析
        enable_sentiment = kwargs.get("enable_sentiment", True)
        if enable_sentiment and unique_results and len(unique_results) > 0:
            logger.info(f"  🎭 开始对搜索结果进行情感分析...")
            sentiment_analysis = self._perform_sentiment_analysis(unique_results)
            if sentiment_analysis:
                # 将情感分析结果添加到响应的parameters中
                integrated_response.parameters["sentiment_analysis"] = (
                    sentiment_analysis
                )
                logger.info(f"  ✅ 情感分析完成")

        return integrated_response

    def _deduplicate_results(self, results: List) -> List:
        """
        去重搜索结果
        """
        seen = set()
        unique_results = []

        for result in results:
            # 使用URL或内容作为去重标识
            identifier = result.url if result.url else result.title_or_content[:100]
            if identifier not in seen:
                seen.add(identifier)
                unique_results.append(result)

        return unique_results

    def _perform_sentiment_analysis(self, results: List) -> Optional[Dict[str, Any]]:
        """
        对搜索结果执行情感分析

        Args:
            results: 搜索结果列表

        Returns:
            情感分析结果字典，如果失败则返回None
        """
        try:
            # 初始化情感分析器（如果尚未初始化且未被禁用）
            if (
                not self.sentiment_analyzer.is_initialized
                and not self.sentiment_analyzer.is_disabled
            ):
                logger.info("    初始化情感分析模型...")
                if not self.sentiment_analyzer.initialize():
                    logger.info("     情感分析模型初始化失败，将直接透传原始文本")
            elif self.sentiment_analyzer.is_disabled:
                logger.info("     情感分析功能已禁用，直接透传原始文本")

            # 将查询结果转换为字典格式
            results_dict = []
            for result in results:
                result_dict = {
                    "content": result.title_or_content,
                    "platform": result.platform,
                    "author": result.author_nickname,
                    "url": result.url,
                    "publish_time": str(result.publish_time)
                    if result.publish_time
                    else None,
                }
                results_dict.append(result_dict)

            # 执行情感分析
            sentiment_analysis = self.sentiment_analyzer.analyze_query_results(
                query_results=results_dict, text_field="content", min_confidence=0.5
            )

            return sentiment_analysis.get("sentiment_analysis")

        except Exception as e:
            logger.exception(f"    ❌ 情感分析过程中发生错误: {str(e)}")
            return None

    def analyze_sentiment_only(self, texts: Union[str, List[str]]) -> Dict[str, Any]:
        """
        独立的情感分析工具

        Args:
            texts: 单个文本或文本列表

        Returns:
            情感分析结果
        """
        logger.info(f"  → 执行独立情感分析")

        try:
            # 初始化情感分析器（如果尚未初始化且未被禁用）
            if (
                not self.sentiment_analyzer.is_initialized
                and not self.sentiment_analyzer.is_disabled
            ):
                logger.info("    初始化情感分析模型...")
                if not self.sentiment_analyzer.initialize():
                    logger.info("     情感分析模型初始化失败，将直接透传原始文本")
            elif self.sentiment_analyzer.is_disabled:
                logger.warning("     情感分析功能已禁用，直接透传原始文本")

            # 执行分析
            if isinstance(texts, str):
                result = self.sentiment_analyzer.analyze_single_text(texts)
                result_dict = result.__dict__
                response = {
                    "success": result.success and result.analysis_performed,
                    "total_analyzed": 1
                    if result.analysis_performed and result.success
                    else 0,
                    "results": [result_dict],
                }
                if not result.analysis_performed:
                    response["success"] = False
                    response["warning"] = (
                        result.error_message or "情感分析功能不可用，已直接返回原始文本"
                    )
                return response
            else:
                texts_list = list(texts)
                batch_result = self.sentiment_analyzer.analyze_batch(
                    texts_list, show_progress=True
                )
                response = {
                    "success": batch_result.analysis_performed
                    and batch_result.success_count > 0,
                    "total_analyzed": batch_result.total_processed
                    if batch_result.analysis_performed
                    else 0,
                    "success_count": batch_result.success_count,
                    "failed_count": batch_result.failed_count,
                    "average_confidence": batch_result.average_confidence
                    if batch_result.analysis_performed
                    else 0.0,
                    "results": [result.__dict__ for result in batch_result.results],
                }
                if not batch_result.analysis_performed:
                    warning = next(
                        (
                            r.error_message
                            for r in batch_result.results
                            if r.error_message
                        ),
                        "情感分析功能不可用，已直接返回原始文本",
                    )
                    response["success"] = False
                    response["warning"] = warning
                return response

        except Exception as e:
            logger.exception(f"    ❌ 情感分析过程中发生错误: {str(e)}")
            return {"success": False, "error": str(e), "results": []}

    def research(self, query: str, save_report: bool = True) -> str:
        """
        执行深度研究

        Args:
            query: 研究查询
            save_report: 是否保存报告到文件

        Returns:
            最终报告内容
        """
        logger.info(f"\n{'=' * 60}")
        logger.info(f"开始深度研究: {query}")
        logger.info(f"{'=' * 60}")

        # 快速检查本地数据库是否有舆情数据
        # 使用 execute_search_tool（走 mock 兼容路径）查询热点内容
        try:
            probe = self.execute_search_tool("search_hot_content", query, time_period="year", limit=1)
            if not probe.results or len(probe.results) == 0:
                logger.warning("本地舆情数据库为空，InsightEngine 退出研究")
                self.state.query = query
                self.state.final_report = ""
                self.state.is_completed = False
                raise RuntimeError(
                    "本地舆情数据库暂无数据，请先运行爬虫采集社交媒体数据。"
                )
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning(f"数据库连通性检查失败: {e}")
            raise RuntimeError(
                f"无法连接到本地舆情数据库，InsightEngine 无法执行。"
            ) from e

        try:
            # 构造初始状态
            initial_state = {
                "query": query,
                "save_report": save_report,
                "max_reflections": self.config.MAX_REFLECTIONS,
            }

            # 执行 LangGraph 图
            result = self.graph.invoke(initial_state, {"recursion_limit": 100})

            # 同步内部 dataclass state（供 get_progress_summary / _extract_citations 等接口使用）
            self.state.query = query
            self.state.report_title = result.get("report_title", "")
            self.state.final_report = result.get("final_report", "")
            self.state.is_completed = result.get("is_completed", False)
            paragraph_dicts = result.get("paragraphs", [])
            self.state.paragraphs = [Paragraph.from_dict(p) for p in paragraph_dicts]

            logger.info("深度研究完成！")
            return result.get("final_report", "")

        except Exception as e:
            logger.exception(f"研究过程中发生错误: {str(e)}")
            raise e

    def get_progress_summary(self) -> Dict[str, Any]:
        """获取进度摘要"""
        return self.state.get_progress_summary()

    def load_state(self, filepath: str):
        """从文件加载状态"""
        self.state = State.load_from_file(filepath)
        logger.info(f"状态已从 {filepath} 加载")

    def save_state(self, filepath: str):
        """保存状态到文件"""
        self.state.save_to_file(filepath)
        logger.info(f"状态已保存到 {filepath}")


def create_agent(config_file: Optional[str] = None) -> DeepSearchAgent:
    """
    创建Deep Search Agent实例的便捷函数

    Args:
        config_file: 配置文件路径

    Returns:
        DeepSearchAgent实例
    """
    config = Settings()  # 以空配置初始化，而从从环境变量初始化
    return DeepSearchAgent(config)
