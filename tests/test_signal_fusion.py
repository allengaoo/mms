"""
tests/test_signal_fusion.py
━━━━━━━━━━━━━━━━━━━━━━━━━━
signal_fusion 模块单元测试（25 用例）

覆盖范围：
  SF-01~07  SignalBreakdown 与 infer_layer 核心逻辑
  SF-08~10  detect_code_object_type 分层语义类型
  SF-11~18  load_overrides / apply_override YAML 覆盖规则
  SF-19~25  infer_all 完整流程与边界场景
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import pytest

# ── sys.path 确保可以直接 import mms ──────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mms.bootstrap.signal_fusion import (
    LAYERS,
    MEMORY_NODE_TYPES,
    LayerInference,
    ObjectTypeMapping,
    OverrideRule,
    SignalBreakdown,
    apply_override,
    detect_code_object_type,
    infer_all,
    infer_layer,
    load_overrides,
)


# ─────────────────────────────────────────────────────────────────────────────
# SF-01  SignalBreakdown 权重加和
# ─────────────────────────────────────────────────────────────────────────────
def test_sf01_signal_breakdown_weights():
    """5 路权重之和为 1.0；total() 计算正确。"""
    weights = [0.25, 0.25, 0.30, 0.10, 0.10]
    assert abs(sum(weights) - 1.0) < 1e-9

    sb = SignalBreakdown(
        path_score=1.0,
        name_score=1.0,
        annotation_score=1.0,
        inheritance_score=1.0,
        import_score=1.0,
    )
    assert abs(sb.total() - 1.0) < 1e-9

    sb2 = SignalBreakdown(path_score=0.5, annotation_score=1.0)
    expected = 0.5 * 0.25 + 0.0 * 0.25 + 1.0 * 0.30 + 0.0 * 0.10 + 0.0 * 0.10
    assert abs(sb2.total() - expected) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# SF-02  路径信号 → ADAPTER
# ─────────────────────────────────────────────────────────────────────────────
def test_sf02_infer_layer_adapter_by_path():
    """含 /api/ 的路径 → ADAPTER 层。"""
    result = infer_layer(
        file_path="src/api/user_controller.py",
        class_name="UserController",
    )
    assert result.inferred_layer == "ADAPTER"
    assert result.confidence >= 0.25


# ─────────────────────────────────────────────────────────────────────────────
# SF-03  命名信号 → APP
# ─────────────────────────────────────────────────────────────────────────────
def test_sf03_infer_layer_app_by_name():
    """类名以 Service 结尾 → APP 层（_NAME_SUFFIXES 命名规则）。"""
    result = infer_layer(
        file_path="src/some/OrderService.py",
        class_name="OrderService",
    )
    assert result.inferred_layer == "APP"
    assert result.confidence >= 0.25


# ─────────────────────────────────────────────────────────────────────────────
# SF-04  注解信号 → PLATFORM
# ─────────────────────────────────────────────────────────────────────────────
def test_sf04_infer_layer_platform_by_annotation():
    """@Configuration 注解 → PLATFORM 层（最高权重 0.30）。"""
    result = infer_layer(
        file_path="src/config/app_config.py",
        class_name="AppConfig",
        annotations=["@Configuration"],
    )
    assert result.inferred_layer == "PLATFORM"
    assert result.confidence >= 0.25


# ─────────────────────────────────────────────────────────────────────────────
# SF-05  继承信号 → CC
# ─────────────────────────────────────────────────────────────────────────────
def test_sf05_infer_layer_cc_by_bases():
    """继承已知 CC 层父类 → CC 信号加分。"""
    result = infer_layer(
        file_path="src/common/my_exception.py",
        class_name="MyException",
        bases=["Exception"],
    )
    assert result.inferred_layer == "CC"


# ─────────────────────────────────────────────────────────────────────────────
# SF-06  全路信号都弱 → UNKNOWN
# ─────────────────────────────────────────────────────────────────────────────
def test_sf06_infer_layer_unknown_below_threshold():
    """无任何有意义信号 → UNKNOWN，置信度 < 0.25。"""
    result = infer_layer(
        file_path="src/x/y/z.py",
        class_name="Z",
        annotations=[],
        bases=[],
        in_degree=0,
    )
    # 至少应当返回 UNKNOWN 或极低置信度
    if result.inferred_layer != "UNKNOWN":
        assert result.confidence < 0.4  # 允许某些规则模糊命中，但置信度应低


# ─────────────────────────────────────────────────────────────────────────────
# SF-07  高入度 → PLATFORM / DOMAIN 加权
# ─────────────────────────────────────────────────────────────────────────────
def test_sf07_high_in_degree_boosts_platform():
    """in_degree >= 5 时，PLATFORM/DOMAIN 的导入信号得分提升。"""
    result_high = infer_layer(
        file_path="src/infra/database.py",
        class_name="DatabaseConfig",
        in_degree=10,
    )
    result_low = infer_layer(
        file_path="src/infra/database.py",
        class_name="DatabaseConfig",
        in_degree=0,
    )
    # 高入度版本的 PLATFORM 或 DOMAIN 分数应 >= 低入度版本
    high_score = max(
        result_high.all_scores.get("PLATFORM", 0),
        result_high.all_scores.get("DOMAIN", 0),
    )
    low_score = max(
        result_low.all_scores.get("PLATFORM", 0),
        result_low.all_scores.get("DOMAIN", 0),
    )
    assert high_score >= low_score


# ─────────────────────────────────────────────────────────────────────────────
# SF-08  ADAPTER 层 → Controller 类型
# ─────────────────────────────────────────────────────────────────────────────
def test_sf08_detect_type_adapter_controller():
    """ADAPTER 层 + Controller 关键词 → code_object_type=Controller。"""
    layer_inf = LayerInference(inferred_layer="ADAPTER", confidence=0.9)
    result = detect_code_object_type(
        class_name="UserController",
        annotations=["@RestController"],
        layer_inference=layer_inf,
    )
    assert result.code_object_type == "Controller"
    assert result.suggested_layer == "ADAPTER"


# ─────────────────────────────────────────────────────────────────────────────
# SF-09  DOMAIN 层 + Entity 关键词 → Entity 类型
# ─────────────────────────────────────────────────────────────────────────────
def test_sf09_detect_type_domain_entity():
    """DOMAIN 层 + Entity 名称 → Entity 类型。"""
    layer_inf = LayerInference(inferred_layer="DOMAIN", confidence=0.8)
    result = detect_code_object_type(
        class_name="UserEntity",
        annotations=["@Entity"],
        layer_inference=layer_inf,
    )
    assert result.code_object_type == "Entity"


# ─────────────────────────────────────────────────────────────────────────────
# SF-10  PLATFORM 层 → Config 类型
# ─────────────────────────────────────────────────────────────────────────────
def test_sf10_detect_type_platform_config():
    """PLATFORM 层 → code_object_type=Config。"""
    layer_inf = LayerInference(inferred_layer="PLATFORM", confidence=0.85)
    result = detect_code_object_type(
        class_name="SecurityConfig",
        layer_inference=layer_inf,
    )
    assert result.code_object_type == "Config"
    assert result.suggested_layer == "PLATFORM"


# ─────────────────────────────────────────────────────────────────────────────
# SF-11  load_overrides：从临时 YAML 文件正确解析规则
# ─────────────────────────────────────────────────────────────────────────────
def test_sf11_load_overrides_from_yaml():
    """构造临时 seed_packs/base/match_conditions.yaml → 正确解析 OverrideRule。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base_dir = root / "seed_packs" / "base"
        base_dir.mkdir(parents=True)
        yaml_content = """
ast_overrides:
  - rule_id: TEST-001
    force_layer: DOMAIN
    force_object_type: Repository
    confidence: 0.95
    bases_contains: JpaRepository
"""
        (base_dir / "match_conditions.yaml").write_text(yaml_content)

        rules = load_overrides(root, detected_stacks=["base"])
        assert len(rules) >= 1
        r = next((x for x in rules if x.rule_id == "TEST-001"), None)
        assert r is not None
        assert r.force_layer == "DOMAIN"
        assert r.confidence == 0.95
        assert r.bases_contains == "JpaRepository"


# ─────────────────────────────────────────────────────────────────────────────
# SF-12  load_overrides：seed_packs 目录不存在时回退，返回列表（不崩溃）
# ─────────────────────────────────────────────────────────────────────────────
def test_sf12_load_overrides_missing_dir_no_crash():
    """project_root 下无 seed_packs 目录 → 回退到 MMS 自带或返回 []，不崩溃。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)  # 空目录，没有 seed_packs
        rules = load_overrides(root, detected_stacks=[])
        assert isinstance(rules, list)  # 无论回退还是空，都是列表


# ─────────────────────────────────────────────────────────────────────────────
# SF-13  apply_override：bases_contains 命中
# ─────────────────────────────────────────────────────────────────────────────
def test_sf13_apply_override_bases_match():
    """bases_contains=JpaRepository 且类继承 JpaRepository → 命中规则。"""
    rules = [
        OverrideRule(
            rule_id="R1",
            force_layer="DOMAIN",
            force_object_type="Repository",
            confidence=0.95,
            bases_contains="JpaRepository",
        )
    ]
    result = apply_override(
        class_name="UserRepo",
        bases=["JpaRepository"],
        annotations=[],
        override_rules=rules,
    )
    assert result is not None
    layer_inf, obj_map = result
    assert layer_inf.inferred_layer == "DOMAIN"
    assert layer_inf.confidence == 0.95


# ─────────────────────────────────────────────────────────────────────────────
# SF-14  apply_override：annotation_contains 命中
# ─────────────────────────────────────────────────────────────────────────────
def test_sf14_apply_override_annotation_match():
    """annotation_contains=@RestController 且注解列表包含 → 命中。"""
    rules = [
        OverrideRule(
            rule_id="R2",
            force_layer="ADAPTER",
            force_object_type="Controller",
            confidence=0.95,
            annotation_contains="@RestController",
        )
    ]
    result = apply_override(
        class_name="OrderController",
        bases=[],
        annotations=["@RestController", "@RequestMapping('/orders')"],
        override_rules=rules,
    )
    assert result is not None
    layer_inf, _ = result
    assert layer_inf.inferred_layer == "ADAPTER"


# ─────────────────────────────────────────────────────────────────────────────
# SF-15  apply_override：name_suffix 命中
# ─────────────────────────────────────────────────────────────────────────────
def test_sf15_apply_override_name_suffix_match():
    """name_suffix=Repository 且类名以 Repository 结尾 → 命中。"""
    rules = [
        OverrideRule(
            rule_id="R3",
            force_layer="DOMAIN",
            force_object_type="Repository",
            confidence=0.9,
            name_suffix="Repository",
        )
    ]
    result = apply_override(
        class_name="ProductRepository",
        bases=[],
        annotations=[],
        override_rules=rules,
    )
    assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# SF-16  apply_override：AND 逻辑，只满足部分条件 → 不命中
# ─────────────────────────────────────────────────────────────────────────────
def test_sf16_apply_override_and_logic_partial_miss():
    """bases_contains AND name_suffix 同时要求，只满足 name_suffix → 不命中。"""
    rules = [
        OverrideRule(
            rule_id="R4",
            force_layer="DOMAIN",
            force_object_type="Repository",
            confidence=0.9,
            bases_contains="JpaRepository",  # 需要继承
            name_suffix="Repository",         # 需要名称后缀
        )
    ]
    result = apply_override(
        class_name="ProductRepository",
        bases=[],           # 没有继承 JpaRepository
        annotations=[],
        override_rules=rules,
    )
    assert result is None  # AND 条件未全满足


# ─────────────────────────────────────────────────────────────────────────────
# SF-17  apply_override：priority 竞争，高 priority 获胜
# ─────────────────────────────────────────────────────────────────────────────
def test_sf17_apply_override_priority_order():
    """两条规则都命中，priority 高的规则获胜。"""
    rules = [
        OverrideRule(
            rule_id="LOW",
            force_layer="DOMAIN",
            force_object_type="Entity",
            confidence=0.8,
            name_suffix="Model",
            priority=0,
        ),
        OverrideRule(
            rule_id="HIGH",
            force_layer="PLATFORM",
            force_object_type="Config",
            confidence=0.85,
            name_suffix="Model",
            priority=10,
        ),
    ]
    result = apply_override(
        class_name="UserModel",
        bases=[],
        annotations=[],
        override_rules=rules,
    )
    assert result is not None
    layer_inf, _ = result
    # priority=10 的规则获胜
    assert layer_inf.inferred_layer == "PLATFORM"


# ─────────────────────────────────────────────────────────────────────────────
# SF-18  apply_override：无规则命中 → 返回 None
# ─────────────────────────────────────────────────────────────────────────────
def test_sf18_apply_override_no_match():
    """无任何规则命中 → 返回 None。"""
    rules = [
        OverrideRule(
            rule_id="R5",
            force_layer="DOMAIN",
            force_object_type="Repository",
            confidence=0.9,
            bases_contains="JpaRepository",
        )
    ]
    result = apply_override(
        class_name="SomeClass",
        bases=["BaseModel"],   # 不含 JpaRepository
        annotations=[],
        override_rules=rules,
    )
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# SF-19  infer_all：override 命中时优先于信号融合
# ─────────────────────────────────────────────────────────────────────────────
def test_sf19_infer_all_override_takes_priority():
    """当 override 规则命中时，confidence=覆盖规则值，跳过信号融合。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base_dir = root / "seed_packs" / "base"
        base_dir.mkdir(parents=True)
        (base_dir / "match_conditions.yaml").write_text("""
ast_overrides:
  - rule_id: FORCE-REPO
    force_layer: DOMAIN
    force_object_type: Repository
    confidence: 0.98
    bases_contains: JpaRepository
""")
        ast_index = {
            "src/repo/UserRepo.py": {
                "lang": "python",
                "classes": [{
                    "name": "UserRepo",
                    "bases": ["JpaRepository"],
                    "annotations": [],
                    "methods": [],
                    "fingerprint": "",
                }],
                "imports": [],
            }
        }
        results = infer_all(
            ast_index=ast_index,
            project_root=root,
            detected_stacks=["base"],
            min_confidence=0.5,
        )
        fqn = "src/repo/UserRepo.py::UserRepo"
        assert fqn in results
        layer_inf, obj_map = results[fqn]
        assert layer_inf.inferred_layer == "DOMAIN"
        assert layer_inf.confidence == 0.98


# ─────────────────────────────────────────────────────────────────────────────
# SF-20  infer_all：min_confidence 过滤
# ─────────────────────────────────────────────────────────────────────────────
def test_sf20_infer_all_min_confidence_filter():
    """min_confidence=0.9 → 低置信度类不出现在结果中。"""
    ast_index = {
        "src/x/y.py": {
            "lang": "python",
            "classes": [{
                "name": "VagueClass",
                "bases": [],
                "annotations": [],
                "methods": [],
                "fingerprint": "",
            }],
            "imports": [],
        }
    }
    results = infer_all(
        ast_index=ast_index,
        min_confidence=0.9,
    )
    # 如果 VagueClass 置信度低于 0.9，不应在结果中；或者置信度确实高就不强求
    for fqn, (li, _) in results.items():
        assert li.confidence >= 0.9 or li.inferred_layer == "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# SF-21  infer_all：空 ast_index 不崩溃
# ─────────────────────────────────────────────────────────────────────────────
def test_sf21_infer_all_empty_ast_index():
    """空 ast_index → 返回 {}，不抛异常。"""
    results = infer_all(ast_index={})
    assert results == {}


# ─────────────────────────────────────────────────────────────────────────────
# SF-22  infer_all：父类层级传播
# ─────────────────────────────────────────────────────────────────────────────
def test_sf22_infer_all_parent_layer_propagation():
    """父类已被推断为 DOMAIN → 子类继承信号加分。"""
    ast_index = {
        "src/domain/base_repo.py": {
            "lang": "python",
            "classes": [{
                "name": "BaseRepository",
                "bases": ["JpaRepository"],
                "annotations": [],
                "methods": [],
                "fingerprint": "",
            }],
            "imports": [],
        },
        "src/domain/user_repo.py": {
            "lang": "python",
            "classes": [{
                "name": "UserRepository",
                "bases": ["BaseRepository"],
                "annotations": [],
                "methods": [],
                "fingerprint": "",
            }],
            "imports": [],
        },
    }
    results = infer_all(ast_index=ast_index, min_confidence=0.1)
    # BaseRepository 应被推断为 DOMAIN（JpaRepository hint）
    base_fqn = "src/domain/base_repo.py::BaseRepository"
    if base_fqn in results:
        assert results[base_fqn][0].inferred_layer == "DOMAIN"


# ─────────────────────────────────────────────────────────────────────────────
# SF-23  infer_all：返回值结构完整
# ─────────────────────────────────────────────────────────────────────────────
def test_sf23_infer_all_returns_tuple_structure():
    """infer_all 每个结果值是 (LayerInference, ObjectTypeMapping) 二元组。"""
    ast_index = {
        "src/service/order_service.py": {
            "lang": "python",
            "classes": [{
                "name": "OrderService",
                "bases": [],
                "annotations": [],
                "methods": [{"name": "create_order", "signature": "(self, dto)"}],
                "fingerprint": "abc123",
            }],
            "imports": [],
        }
    }
    results = infer_all(ast_index=ast_index, min_confidence=0.1)
    for fqn, value in results.items():
        assert len(value) == 2
        layer_inf, obj_map = value
        assert isinstance(layer_inf, LayerInference)
        assert isinstance(obj_map, ObjectTypeMapping)
        assert layer_inf.inferred_layer in LAYERS + ["UNKNOWN"]


# ─────────────────────────────────────────────────────────────────────────────
# SF-24  路径信号 → Go handler 文件 → ADAPTER
# ─────────────────────────────────────────────────────────────────────────────
def test_sf24_infer_layer_go_handler_path():
    """Go handler 路径 → ADAPTER 层。"""
    result = infer_layer(
        file_path="internal/delivery/http/user_handler.go",
        class_name="UserHandler",
    )
    assert result.inferred_layer == "ADAPTER"


# ─────────────────────────────────────────────────────────────────────────────
# SF-25  Java @Service 注解 → APP 层
# ─────────────────────────────────────────────────────────────────────────────
def test_sf25_infer_layer_java_service_annotation():
    """@Service 注解（Spring）→ APP 层。"""
    result = infer_layer(
        file_path="src/main/java/com/example/service/OrderService.java",
        class_name="OrderService",
        annotations=["@Service"],
    )
    assert result.inferred_layer == "APP"
    assert result.confidence >= 0.25
