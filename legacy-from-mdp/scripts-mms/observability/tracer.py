"""
Trace ID 生成器

格式：MMS-{YYYYMMDD}-{6位小写 hex}
示例：MMS-20260411-a1b2c3

设计原则：
  - 纯 stdlib，零依赖
  - 每次调用保证唯一（secrets.token_hex 的随机性）
  - 可在日志、文件名、审计记录中直接使用
"""
import datetime
import secrets


def new_trace_id() -> str:
    """
    生成全局唯一的 MMS Trace ID。

    Returns:
        格式为 "MMS-YYYYMMDD-xxxxxx" 的字符串

    Example:
        tid = new_trace_id()  # "MMS-20260411-a1b2c3"
    """
    date_str = datetime.date.today().strftime("%Y%m%d")
    hex_suffix = secrets.token_hex(3)   # 3 bytes = 6 位 hex
    return f"MMS-{date_str}-{hex_suffix}"
