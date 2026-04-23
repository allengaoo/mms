# 模版：跨层 · 单文件 Bug 修复（小模型极简版）
# 适用：已知根因的单文件修复 / 快速 Hotfix
# Token 预算：≤2K（最小上下文原则）

---

## [TASK] Bug 修复
**文件**：`{文件路径}`
**现象**：{一句话描述症状}
**根因**：{一句话描述根因}（来自 ISSUE-REGISTRY 或调试日志）
**修复方向**：{一句话说明修复方法}

---

## [MEMORY] 相关记忆（0-1条，精准命中）
{如命中 MEM-L-001 等记忆，直接复制其"禁止项"和"HOW 正确写法"}

---

## [CONSTRAINTS] 本次修复必守（3条最小集合）
- ✅ 禁止 `print()`，用 `structlog`
- ✅ 修复后必须更新 `docs/hotfix/ISSUE-REGISTRY.md`（标记 FIXED）
- ✅ 如果是新坑点，追加到 `docs/memory/shared/` 对应分层记忆文件

---

## [OUTPUT] 输出格式（极简）
1. 修复的 diff（old → new，最多 20 行）
2. 验证命令（curl / pytest 命令一行）
3. 是否需要重建镜像：是 / 否

---

_提示：单文件修复使用 fast model，无需加载完整 Manifest。若根因涉及多文件，切换到对应分层模版。_
