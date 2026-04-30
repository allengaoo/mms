"""
src/mms/bootstrap — Bootstrap v2 模块包

核心模块：
  signal_fusion        — fn_infer_layer / fn_detect_code_object_type（五路信号融合）
  code_graph_builder   — fn_build_code_graph（代码依赖图）
  memory_seed_generator — 初始 MemoryNode 生成器
  ontology_populator   — Bootstrap v2 顶层编排（取代 cmd_bootstrap 中的简单逻辑）
"""
from mms.bootstrap.ontology_populator import bootstrap_project, BootstrapV2Report

__all__ = ["bootstrap_project", "BootstrapV2Report"]
