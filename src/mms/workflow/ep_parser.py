"""
workflow/ep_parser.py — 兼容性 re-export 垫片

ep_parser 已迁移至 mms.utils.ep_parser（无状态工具函数，不属于 workflow 层）。
此文件保留以向后兼容，所有符号从新位置 re-export。

新代码请直接使用：
    from mms.utils.ep_parser import parse_ep_by_id, parse_ep_file, ...
"""
from mms.utils.ep_parser import (  # noqa: F401
    # 公开 API
    ParsedEP,
    parse_ep_file,
    parse_ep_by_id,
    # 私有函数（向后兼容：部分测试直接访问）
    _extract_ep_id,
    _extract_title,
    _extract_sections,
    _parse_scope_table,
    _parse_scope_fallback,
    _parse_testing_files,
    _extract_table_rows,
    _normalize_section_key,
    # 编译常量
    _EP_ID_RE,
    _H1_RE,
    _SECTION_RE,
    _UNIT_ID_RE,
    _FILE_PATH_RE,
    _TABLE_ROW_ANY_RE,
    _TEST_FILE_RE,
)
