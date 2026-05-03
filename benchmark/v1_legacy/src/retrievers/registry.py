"""
registry.py — 检索器注册表
===========================
新增检索系统时，只需：
  1. 在 src/retrievers/ 中新建一个继承 BaseRetriever 的类
  2. 在下面的 RETRIEVERS 字典中加一行

不需要修改评估器、报告器或主入口。
"""
from .markdown_retriever import MarkdownRetriever
from .hybrid_rag_retriever import HybridRAGRetriever
from .ontology_retriever import OntologyRetriever

RETRIEVERS = {
    "markdown":   MarkdownRetriever,
    "hybrid_rag": HybridRAGRetriever,
    "ontology":   OntologyRetriever,
    # 未来新增示例：
    # "graph_rag": GraphRAGRetriever,
}


def get_retriever(system_name: str, cfg: dict):
    """
    按系统名称实例化检索器。

    Args:
        system_name: 对应 config/systems.yaml 中的 key
        cfg:         完整的 systems.yaml 配置字典

    Returns:
        BaseRetriever 实例

    Raises:
        ValueError: 系统名称不在注册表中
    """
    cls = RETRIEVERS.get(system_name)
    if cls is None:
        raise ValueError(
            f"未知检索系统: {system_name!r}。"
            f"已注册: {list(RETRIEVERS.keys())}"
        )
    return cls(system_name=system_name, cfg=cfg)
