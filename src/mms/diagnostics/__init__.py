"""
mms.diagnostics — Layer 4 诊断工具包

提供记忆图谱的可视化诊断能力，无需引入复杂的前端框架。
输出为自包含的 HTML 文件（内嵌 CSS/JS），可在浏览器中直接打开。

公开 API：
    from mms.diagnostics.memory_viz import MemoryVizCollector
    from mms.diagnostics.html_renderer import render_html
"""

from mms.diagnostics.memory_viz import MemoryVizCollector
from mms.diagnostics.html_renderer import render_html

__all__ = ["MemoryVizCollector", "render_html"]
