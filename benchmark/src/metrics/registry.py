"""
registry.py — 指标注册表
==========================
新增指标时，在对应的 accuracy.py / efficiency.py 中添加计算函数，
然后在 METRIC_FUNCS 中注册。评估器自动发现并调用所有 enabled 指标。
"""
from . import accuracy, efficiency

METRIC_FUNCS = {
    # 准确性指标
    "layer_accuracy":  accuracy.layer_accuracy,
    "op_accuracy":     accuracy.op_accuracy,
    "recall_at_k":     accuracy.recall_at_k,
    "mrr":             accuracy.mrr,
    "path_validity":   accuracy.path_validity,
    "memory_recall":   accuracy.memory_recall,

    # 效率指标
    "context_tokens":  efficiency.context_tokens,
    "info_density":    efficiency.info_density,
    "actionability":   efficiency.actionability,

    # latency 不在 METRIC_FUNCS 中（直接从 RetrievalResult 读取）
}
