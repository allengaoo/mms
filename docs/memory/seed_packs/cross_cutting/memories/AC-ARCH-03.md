---
id: AC-ARCH-03
layer: PLATFORM
tier: hot
type: arch_constraint
language: all
pack: cross_cutting
about_concepts: [configuration, environment-variables, 12-factor-app, hardcoding, security]
cites_files: []
created_at: "2026-04-27"
---

# 配置值必须来自环境变量，禁止硬编码在代码中

## 约束（Constraint）

所有环境相关的配置（URL、端口、密钥、API Key、超时值）必须通过环境变量或配置中心（如 Nacos、Consul、AWS SSM）读取，**禁止任何形式的硬编码**。

```python
# ❌ 错误：硬编码配置
DATABASE_URL = "mysql://root:password123@localhost:3306/mall"
REDIS_HOST = "192.168.1.100"
SECRET_KEY = "my-super-secret-key-12345"
OPENAI_API_KEY = "sk-proj-abcdefghijklmnop"
```

```python
# ✅ 正确：从环境变量读取（Python + pydantic-settings）
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str                           # 必须提供，无默认值
    redis_host: str = "localhost"               # 有安全默认值
    redis_port: int = 6379
    secret_key: str                             # 必须提供
    openai_api_key: str                         # 必须提供
    request_timeout: int = 30                   # 超时也通过配置控制

    class Config:
        env_file = ".env"   # 本地开发时从 .env 文件读取

settings = Settings()   # 启动时验证，缺失必填配置立即报错
```

## 12 Factor App 原则

> "An app's config is everything that is likely to vary between deploys (staging, production, developer environments, etc). This includes... credentials to external services."

## 安全检测

```bash
# 使用 truffleHog 扫描代码库中的硬编码密钥
trufflehog git file://. --only-verified

# 使用 detect-secrets 预防新增硬编码密钥
detect-secrets scan > .secrets.baseline
detect-secrets audit .secrets.baseline
```

## .env.example 模板

项目根目录必须维护 `.env.example`（提交到 Git），但 `.env`（含真实值）必须在 `.gitignore` 中：

```bash
# .env.example
DATABASE_URL=mysql://user:password@host:3306/dbname
REDIS_HOST=localhost
SECRET_KEY=your-secret-key-here
```

## 参考

- The Twelve-Factor App：[III. Config](https://12factor.net/config)
- OWASP：[Sensitive Data Exposure](https://owasp.org/www-project-top-ten/2017/A3_2017-Sensitive_Data_Exposure)
