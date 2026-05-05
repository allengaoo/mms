#!/usr/bin/env python3
"""
html_renderer.py — 记忆图谱 HTML 渲染器

将 MemoryVizCollector 输出的 VizData 渲染为单个自包含的 HTML 文件。
使用 vis-network（CDN）做图可视化，不引入任何后端服务或打包工具。

三个标签页：
  Tab 1 — 记忆图谱 (Memory Graph)   : vis-network 交互图
  Tab 2 — AST 文件列表 (AST View)  : 按源码文件分组的树状视图
  Tab 3 — AST↔记忆映射 (Mapping)   : 代码类 ↔ 记忆节点的对应表
"""

from __future__ import annotations

import json
from typing import List

from mms.diagnostics.memory_viz import VizData, NodeData, EdgeData, AstMapping


# ── tier → 颜色 ──────────────────────────────────────────────────────────────
_TIER_COLORS = {
    "hot":     "#ef4444",
    "warm":    "#f97316",
    "cold":    "#3b82f6",
    "archive": "#9ca3af",
}

_LAYER_COLORS = {
    "L1_platform":       "#7c3aed",
    "L2_infrastructure": "#1d4ed8",
    "L3_domain":         "#065f46",
    "L4_application":    "#92400e",
    "L5_interface":      "#be185d",
    "CC":                "#374151",
    "BIZ":               "#0e7490",
    "PLATFORM":          "#5b21b6",
}


def _node_to_vis(n: NodeData) -> dict:
    """将 NodeData 转为 vis-network 所需的 JS 节点对象。"""
    bg = _TIER_COLORS.get(n.tier, "#6b7280")
    border = _LAYER_COLORS.get(n.layer, "#374151")
    shape = "dot" if n.tier == "hot" else "ellipse"
    size = {"hot": 18, "warm": 14, "cold": 12, "archive": 9}.get(n.tier, 12)

    drift_marker = " ⚠" if n.ast_drift else ""
    display_label = (n.ast_class or n.id) + drift_marker
    if len(display_label) > 22:
        display_label = display_label[:20] + "…"

    return {
        "id": n.id,
        "label": display_label,
        "title": n.title.replace("\n", "<br>"),
        "color": {
            "background": bg,
            "border": border,
            "highlight": {"background": bg, "border": "#000"},
        },
        "shape": shape,
        "size": size,
        "font": {"color": "#fff", "size": 11},
        "layer": n.layer,
        "tier": n.tier,
        "file_path": n.file_path,
        "ast_file": n.ast_file,
        "ast_class": n.ast_class,
    }


def _edge_to_vis(e: EdgeData, idx: int) -> dict:
    """将 EdgeData 转为 vis-network 所需的边对象。

    边类型：
      - related_to     灰色实线（显式语义关联）
      - impacts        红色实线（变更影响传播）
      - derived_from   绿色实线（知识来源）
      - cites          蓝色实线（代码引用）
      - cites_same_file 浅蓝虚线（同文件隐式共现，Bootstrap 推断）
    """
    color_map = {
        "related_to":      "#6b7280",
        "impacts":         "#dc2626",
        "derived_from":    "#059669",
        "cites":           "#2563eb",
        "cites_same_file": "#93c5fd",
    }
    is_inferred = e.relation == "cites_same_file"
    return {
        "id": idx,
        "from": e.source,
        "to": e.target,
        "label": e.label if not is_inferred else "",
        "title": f"[推断] 共享代码文件" if is_inferred else e.label,
        "color": {"color": color_map.get(e.relation, "#9ca3af"), "opacity": 0.5 if is_inferred else 0.75},
        "arrows": "to" if not is_inferred else "",
        "dashes": is_inferred,
        "width": 1 if is_inferred else 2,
        "font": {"size": 9, "color": "#4b5563"},
        "smooth": {"type": "curvedCW", "roundness": 0.1},
    }


def _build_ast_tree_html(ast_mappings: List[AstMapping]) -> str:
    """按源码文件分组，生成 Tab 2 的 HTML 树状列表。"""
    from collections import defaultdict

    grouped = defaultdict(list)
    for m in ast_mappings:
        grouped[m.source_file].append(m)

    if not grouped:
        return "<p style='color:#6b7280;padding:1rem'>暂无 AST 指针数据。</p>"

    lines = ['<div class="ast-tree">']
    for src_file in sorted(grouped.keys()):
        mappings = grouped[src_file]
        drift_any = any(m.drift for m in mappings)
        drift_icon = " ⚠️" if drift_any else ""
        lines.append(f'<details open><summary class="ast-file">{src_file}{drift_icon}</summary><ul class="ast-classes">')
        for m in sorted(mappings, key=lambda x: x.class_name):
            tier_badge = f'<span class="badge tier-{m.tier}">{m.tier}</span>'
            layer_badge = f'<span class="badge layer-badge">{m.layer}</span>'
            conf_pct = f"{m.confidence:.0%}"
            drift_warn = ' <span class="drift-warn">⚠ drift</span>' if m.drift else ""
            lines.append(
                f'<li>{tier_badge}{layer_badge} '
                f'<code>{m.class_name}</code> → '
                f'<a class="mem-link" href="#" data-id="{m.memory_id}">{m.memory_id}</a> '
                f'<span class="conf">[{conf_pct}]</span>{drift_warn}</li>'
            )
        lines.append("</ul></details>")

    lines.append("</div>")
    return "\n".join(lines)


def _build_mapping_table_html(ast_mappings: List[AstMapping]) -> str:
    """生成 Tab 3 的映射表 HTML。"""
    if not ast_mappings:
        return "<p style='color:#6b7280;padding:1rem'>暂无 AST↔记忆映射数据。</p>"

    rows = []
    for m in sorted(ast_mappings, key=lambda x: (x.source_file, x.class_name)):
        drift_cell = '<span class="drift-warn">⚠ YES</span>' if m.drift else "—"
        conf_pct = f"{m.confidence:.0%}"
        rows.append(
            f"<tr>"
            f"<td><code>{m.source_file}</code></td>"
            f"<td><code>{m.class_name}</code></td>"
            f'<td><a class="mem-link" href="#" data-id="{m.memory_id}">{m.memory_id}</a></td>'
            f"<td>{m.layer}</td>"
            f'<td><span class="badge tier-{m.tier}">{m.tier}</span></td>'
            f"<td>{conf_pct}</td>"
            f"<td>{drift_cell}</td>"
            f"</tr>"
        )

    return (
        '<table class="map-table"><thead><tr>'
        "<th>源码文件</th><th>类名</th><th>记忆节点</th>"
        "<th>层</th><th>Tier</th><th>置信度</th><th>Drift</th>"
        "</tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )


def _build_stats_html(stats: dict) -> str:
    """生成顶部统计卡片 HTML。"""
    ld = stats.get("layer_distribution", {})
    td = stats.get("tier_distribution", {})
    layer_pills = " ".join(
        f'<span class="stat-pill">{k}: {v}</span>' for k, v in sorted(ld.items())
    )
    tier_pills = " ".join(
        f'<span class="stat-pill tier-{k}">{k}: {v}</span>' for k, v in sorted(td.items())
    )
    drift_count = stats.get("drift_count", 0)
    drift_badge = (
        f'<span class="drift-warn"> ⚠ {drift_count} drift</span>'
        if drift_count > 0 else ""
    )

    return f"""
<div class="stats-bar">
  <div class="stat-card">
    <span class="stat-num">{stats.get('total_nodes', 0)}</span>
    <span class="stat-label">记忆节点</span>
  </div>
  <div class="stat-card">
    <span class="stat-num">{stats.get('total_edges', 0)}</span>
    <span class="stat-label">关联边</span>
  </div>
  <div class="stat-card">
    <span class="stat-num">{stats.get('has_ast_count', 0)}</span>
    <span class="stat-label">含 AST 指针</span>
  </div>
  <div class="stat-card">
    <span class="stat-num">{stats.get('total_ast_mappings', 0)}{drift_badge}</span>
    <span class="stat-label">AST 映射</span>
  </div>
  <div class="stat-card wide">
    <span class="stat-label">层分布</span><br>{layer_pills}
  </div>
  <div class="stat-card wide">
    <span class="stat-label">Tier 分布</span><br>{tier_pills}
  </div>
</div>
"""


def render_html(data: VizData, title: str = "MMS 记忆图谱诊断") -> str:
    """
    将 VizData 渲染为完整的自包含 HTML 字符串。

    Args:
        data:  MemoryVizCollector.collect() 的返回值
        title: 页面标题

    Returns:
        str: 完整 HTML 文档字符串（可直接写入 .html 文件）
    """
    vis_nodes = [_node_to_vis(n) for n in data.nodes]
    vis_edges = [_edge_to_vis(e, i) for i, e in enumerate(data.edges)]

    nodes_json = json.dumps(vis_nodes, ensure_ascii=False)
    edges_json = json.dumps(vis_edges, ensure_ascii=False)

    ast_tree_html = _build_ast_tree_html(data.ast_mappings)
    mapping_table_html = _build_mapping_table_html(data.ast_mappings)
    stats_html = _build_stats_html(data.stats)

    # 图例 JSON（给 JS 使用）
    layer_colors_json = json.dumps(_LAYER_COLORS, ensure_ascii=False)
    tier_colors_json = json.dumps(_TIER_COLORS, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — {data.project_name}</title>
<script src="https://unpkg.com/vis-network@9.1.9/dist/vis-network.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f8fafc; color: #1e293b; }}
  header {{ background: #1e293b; color: #f1f5f9; padding: 0.75rem 1.5rem;
             display: flex; align-items: center; gap: 1rem; }}
  header h1 {{ margin: 0; font-size: 1.1rem; font-weight: 600; }}
  header .subtitle {{ font-size: 0.8rem; color: #94a3b8; }}

  /* Stats bar */
  .stats-bar {{ display: flex; flex-wrap: wrap; gap: 0.75rem; padding: 0.75rem 1rem;
                background: #fff; border-bottom: 1px solid #e2e8f0; }}
  .stat-card {{ background: #f1f5f9; border-radius: 8px; padding: 0.4rem 0.8rem;
                min-width: 80px; text-align: center; }}
  .stat-card.wide {{ text-align: left; min-width: 200px; }}
  .stat-num {{ font-size: 1.3rem; font-weight: 700; color: #1e293b; display: block; }}
  .stat-label {{ font-size: 0.7rem; color: #64748b; }}
  .stat-pill {{ display: inline-block; background: #e2e8f0; border-radius: 4px;
                padding: 1px 6px; font-size: 0.7rem; margin: 2px; }}

  /* Tabs */
  .tab-bar {{ display: flex; background: #fff; border-bottom: 2px solid #e2e8f0;
              padding: 0 1rem; }}
  .tab-btn {{ padding: 0.6rem 1.2rem; border: none; background: none; cursor: pointer;
              font-size: 0.9rem; color: #64748b; border-bottom: 2px solid transparent;
              margin-bottom: -2px; transition: all 0.15s; }}
  .tab-btn.active {{ color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }}
  .tab-btn:hover {{ color: #1e293b; }}

  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}

  /* Graph */
  #graph-container {{ width: 100%; height: calc(100vh - 220px); background: #fff;
                      border-bottom: 1px solid #e2e8f0; }}

  /* Controls */
  .graph-controls {{ display: flex; gap: 0.5rem; padding: 0.5rem 1rem;
                     background: #f8fafc; border-bottom: 1px solid #e2e8f0;
                     flex-wrap: wrap; align-items: center; font-size: 0.8rem; }}
  .graph-controls label {{ color: #64748b; }}
  .graph-controls select, .graph-controls input {{
    border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px 6px;
    font-size: 0.8rem; background: #fff; }}
  .graph-controls button {{
    background: #2563eb; color: #fff; border: none; border-radius: 4px;
    padding: 3px 10px; cursor: pointer; font-size: 0.8rem; }}

  /* Legend */
  .legend {{ display: flex; gap: 1rem; flex-wrap: wrap; align-items: center; }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; font-size: 0.75rem; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}

  /* Node detail panel */
  #node-detail {{ position: fixed; right: 0; top: 0; width: 300px; height: 100vh;
                  background: #fff; border-left: 1px solid #e2e8f0; padding: 1rem;
                  overflow-y: auto; transform: translateX(100%);
                  transition: transform 0.2s; z-index: 100; box-shadow: -4px 0 12px rgba(0,0,0,.1); }}
  #node-detail.open {{ transform: translateX(0); }}
  #node-detail .close-btn {{ float: right; cursor: pointer; font-size: 1.2rem; color: #6b7280; }}
  #node-detail h3 {{ margin-top: 0; font-size: 1rem; word-break: break-all; }}
  #node-detail .detail-row {{ font-size: 0.8rem; margin: 4px 0; }}
  #node-detail .detail-label {{ color: #6b7280; font-weight: 600; }}

  /* AST Tree */
  .ast-tree {{ padding: 1rem; max-height: calc(100vh - 200px); overflow-y: auto; }}
  .ast-tree details {{ margin: 0.5rem 0; }}
  .ast-file {{ cursor: pointer; font-weight: 600; font-size: 0.9rem; color: #1e293b;
               padding: 4px 6px; background: #f1f5f9; border-radius: 4px; }}
  .ast-classes {{ list-style: none; padding-left: 1.5rem; margin: 4px 0; }}
  .ast-classes li {{ padding: 3px 0; font-size: 0.82rem; border-bottom: 1px solid #f1f5f9; }}

  /* Mapping table */
  .map-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  .map-table th {{ background: #1e293b; color: #f1f5f9; padding: 6px 10px;
                   text-align: left; position: sticky; top: 0; }}
  .map-table td {{ padding: 5px 10px; border-bottom: 1px solid #e2e8f0; }}
  .map-table tr:hover {{ background: #f8fafc; }}
  .map-table-wrap {{ max-height: calc(100vh - 200px); overflow-y: auto; }}

  /* Badges */
  .badge {{ display: inline-block; border-radius: 3px; padding: 1px 5px;
            font-size: 0.68rem; font-weight: 600; margin-right: 3px; color: #fff; }}
  .tier-hot     {{ background: #ef4444; }}
  .tier-warm    {{ background: #f97316; }}
  .tier-cold    {{ background: #3b82f6; }}
  .tier-archive {{ background: #9ca3af; }}
  .layer-badge  {{ background: #374151; }}
  .conf {{ color: #9ca3af; font-size: 0.75rem; }}
  .drift-warn {{ color: #dc2626; font-weight: 600; }}
  a.mem-link {{ color: #2563eb; text-decoration: none; cursor: pointer; }}
  a.mem-link:hover {{ text-decoration: underline; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>🧠 MMS 记忆图谱诊断</h1>
    <div class="subtitle">项目: {data.project_name} &nbsp;|&nbsp; 数据目录: {data.memory_root}</div>
  </div>
</header>

{stats_html}

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('graph', this)">📊 记忆图谱</button>
  <button class="tab-btn" onclick="switchTab('ast', this)">🌳 AST 文件视图</button>
  <button class="tab-btn" onclick="switchTab('mapping', this)">🔗 AST↔记忆映射</button>
</div>

<!-- Tab 1: Memory Graph -->
<div id="tab-graph" class="tab-panel active">
  <div class="graph-controls">
    <label>筛选层:
      <select id="filter-layer" onchange="applyFilter()">
        <option value="">全部</option>
        <option value="L1_platform">L1_platform</option>
        <option value="L2_infrastructure">L2_infrastructure</option>
        <option value="L3_domain">L3_domain</option>
        <option value="L4_application">L4_application</option>
        <option value="L5_interface">L5_interface</option>
        <option value="CC">CC</option>
        <option value="BIZ">BIZ</option>
        <option value="PLATFORM">PLATFORM</option>
      </select>
    </label>
    <label>筛选 Tier:
      <select id="filter-tier" onchange="applyFilter()">
        <option value="">全部</option>
        <option value="hot">🔴 hot</option>
        <option value="warm">🟠 warm</option>
        <option value="cold">🔵 cold</option>
        <option value="archive">⚫ archive</option>
      </select>
    </label>
    <label>搜索 ID/类名:
      <input id="search-input" type="text" placeholder="输入 ID 或类名..." oninput="applyFilter()" style="width:160px">
    </label>
    <button onclick="resetView()">重置视图</button>
    <button onclick="fitGraph()">适应窗口</button>
    <div class="legend">
      <b style="font-size:0.72rem;color:#374151">节点：</b>
      <span class="legend-item"><span class="legend-dot" style="background:#ef4444"></span>hot</span>
      <span class="legend-item"><span class="legend-dot" style="background:#f97316"></span>warm</span>
      <span class="legend-item"><span class="legend-dot" style="background:#3b82f6"></span>cold</span>
      <span class="legend-item"><span class="legend-dot" style="background:#9ca3af"></span>archive</span>
      <b style="font-size:0.72rem;color:#374151;margin-left:0.5rem">边：</b>
      <span class="legend-item"><span style="display:inline-block;width:20px;height:2px;background:#6b7280;margin-right:2px"></span>related</span>
      <span class="legend-item"><span style="display:inline-block;width:20px;height:2px;background:#dc2626;margin-right:2px"></span>impacts</span>
      <span class="legend-item"><span style="display:inline-block;width:20px;height:2px;background:#059669;margin-right:2px"></span>derived</span>
      <span class="legend-item"><span style="display:inline-block;width:20px;height:2px;border-top:2px dashed #93c5fd;margin-right:2px"></span>同文件(推断)</span>
    </div>
  </div>
  <div id="graph-container"></div>
</div>

<!-- Tab 2: AST View -->
<div id="tab-ast" class="tab-panel">
  {ast_tree_html}
</div>

<!-- Tab 3: Mapping Table -->
<div id="tab-mapping" class="tab-panel">
  <div class="map-table-wrap">
    {mapping_table_html}
  </div>
</div>

<!-- Node detail side panel -->
<div id="node-detail">
  <span class="close-btn" onclick="closeDetail()">✕</span>
  <h3 id="detail-id">—</h3>
  <div id="detail-content"></div>
</div>

<script>
// ── 数据 ────────────────────────────────────────────────────────────────────
const ALL_NODES = {nodes_json};
const ALL_EDGES = {edges_json};
const LAYER_COLORS = {layer_colors_json};
const TIER_COLORS  = {tier_colors_json};

// ── vis-network 初始化 ──────────────────────────────────────────────────────
let network, nodesDs, edgesDs;

function initGraph(nodes, edges) {{
  const container = document.getElementById('graph-container');
  nodesDs = new vis.DataSet(nodes);
  edgesDs = new vis.DataSet(edges);

  const opts = {{
    physics: {{
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {{ gravitationalConstant: -60, centralGravity: 0.005, springLength: 120 }},
      stabilization: {{ iterations: 150, updateInterval: 25 }},
    }},
    interaction: {{ hover: true, tooltipDelay: 200, navigationButtons: true, keyboard: true }},
    nodes: {{ borderWidth: 2, shadow: true }},
    edges: {{ width: 1.5, shadow: false }},
  }};

  network = new vis.Network(container, {{ nodes: nodesDs, edges: edgesDs }}, opts);

  network.on('click', function(params) {{
    if (params.nodes.length > 0) {{
      showDetail(params.nodes[0]);
    }}
  }});
}}

initGraph(ALL_NODES, ALL_EDGES);

// ── 过滤 ────────────────────────────────────────────────────────────────────
function applyFilter() {{
  const layer  = document.getElementById('filter-layer').value;
  const tier   = document.getElementById('filter-tier').value;
  const search = document.getElementById('search-input').value.toLowerCase();

  const filtered = ALL_NODES.filter(n => {{
    if (layer  && n.layer !== layer)  return false;
    if (tier   && n.tier  !== tier)   return false;
    if (search && !n.id.toLowerCase().includes(search)
               && !n.ast_class.toLowerCase().includes(search)) return false;
    return true;
  }});

  const filteredIds = new Set(filtered.map(n => n.id));
  const filteredEdges = ALL_EDGES.filter(e => filteredIds.has(e.from) && filteredIds.has(e.to));

  nodesDs.clear(); nodesDs.add(filtered);
  edgesDs.clear(); edgesDs.add(filteredEdges);
  network.fit({{ animation: {{ duration: 400, easingFunction: 'easeInOutQuad' }} }});
}}

function resetView() {{
  document.getElementById('filter-layer').value = '';
  document.getElementById('filter-tier').value  = '';
  document.getElementById('search-input').value = '';
  nodesDs.clear(); nodesDs.add(ALL_NODES);
  edgesDs.clear(); edgesDs.add(ALL_EDGES);
  network.fit();
}}

function fitGraph() {{ network.fit({{ animation: true }}); }}

// ── 节点详情面板 ─────────────────────────────────────────────────────────────
function showDetail(nodeId) {{
  const n = ALL_NODES.find(x => x.id === nodeId);
  if (!n) return;
  document.getElementById('detail-id').textContent = n.id;
  const drift = n.ast_file ? (n.title.includes('Drift: ⚠️') ? '⚠️ YES' : 'No') : '—';
  document.getElementById('detail-content').innerHTML = `
    <div class="detail-row"><span class="detail-label">Layer</span>: ${{n.layer}}</div>
    <div class="detail-row"><span class="detail-label">Tier</span>: ${{n.tier}}</div>
    <div class="detail-row"><span class="detail-label">类名</span>: ${{n.ast_class || '—'}}</div>
    <div class="detail-row"><span class="detail-label">源码文件</span>: <code style="font-size:.75rem;word-break:break-all">${{n.ast_file || '—'}}</code></div>
    <div class="detail-row"><span class="detail-label">Drift</span>: ${{drift}}</div>
    <div class="detail-row"><span class="detail-label">记忆文件</span>: <code style="font-size:.75rem;word-break:break-all">${{n.file_path}}</code></div>
    <hr style="margin:.5rem 0">
    <div style="font-size:.78rem;color:#64748b;white-space:pre-wrap">${{n.title.replace(/<br>/g,'\\n')}}</div>
  `;
  document.getElementById('node-detail').classList.add('open');
}}

function closeDetail() {{
  document.getElementById('node-detail').classList.remove('open');
}}

// ── Tab 切换 ─────────────────────────────────────────────────────────────────
function switchTab(name, btn) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
  if (name === 'graph') {{ network && network.redraw(); }}
}}

// ── AST Tab 中的 mem-link 点击跳转到 graph ──────────────────────────────────
document.addEventListener('click', function(e) {{
  const a = e.target.closest('a.mem-link');
  if (!a) return;
  e.preventDefault();
  const id = a.dataset.id;
  // 切换到图谱 tab
  switchTab('graph', document.querySelector('.tab-btn'));
  document.querySelector('.tab-btn').classList.add('active');
  // 聚焦节点
  setTimeout(() => {{
    if (network) {{
      network.selectNodes([id]);
      network.focus(id, {{ scale: 1.5, animation: true }});
      showDetail(id);
    }}
  }}, 200);
}});
</script>
</body>
</html>"""
