---
id: AC-ARCH-04
layer: CC
tier: hot
type: arch_constraint
language: all
pack: cross_cutting
about_concepts: [logging, sensitive-data, pii, security, data-masking]
cites_files: []
created_at: "2026-04-27"
---

# 日志输出禁止明文打印敏感信息

## 约束（Constraint）

日志输出（无论是结构化日志还是 print）**禁止明文记录**密码、Token、PII（个人身份信息）。必须使用脱敏工具处理后再输出。

```python
# ❌ 错误：明文记录敏感信息
logger.info(f"User login: email={email}, password={password}")  # 密码明文！
logger.debug(f"API call with token: {api_token}")              # Token 明文！
logger.error(f"Payment failed: card_number={card_number}")     # 卡号明文！
```

```python
# ✅ 正确：脱敏后记录
def mask_email(email: str) -> str:
    parts = email.split("@")
    return f"{parts[0][:2]}***@{parts[1]}"   # ab***@example.com

def mask_token(token: str) -> str:
    return f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"

logger.info("user_login_attempt", email=mask_email(email))   # ✅ 脱敏
logger.info("api_call", token=mask_token(api_token))         # ✅ 脱敏
```

## 结构化日志脱敏中间件

```python
# Python structlog：全局处理器自动脱敏
SENSITIVE_KEYS = {"password", "token", "secret", "api_key", "card_number", "cvv"}

def redact_sensitive(logger, method, event_dict):
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict

structlog.configure(
    processors=[redact_sensitive, ...]
)
```

## 常见敏感字段清单

| 类别 | 字段名示例 |
|---|---|
| 认证凭证 | password, passwd, secret, api_key, token, jwt |
| 支付信息 | card_number, cvv, account_number |
| PII | ssn, id_card, phone（需部分脱敏）, email（需部分脱敏）|
| 系统配置 | database_url（含密码部分）, private_key |

## 参考

- GDPR：日志记录 PII 需要合法基础，建议最小化收集
- OWASP：[Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
