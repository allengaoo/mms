# Enterprise Benchmark: mall 订单服务模块

## 来源
- **项目**: [macrozheng/mall](https://github.com/macrozheng/mall)（Java Spring Boot 电商平台，77k+ Stars）
- **模块**: `mall-admin` 订单管理模块
- **代码版本**: v1.0.0（2022-07-01 附近的 commit）
- **选择理由**: 典型的 Spring Boot + MyBatis + 分层架构项目，有完整 CRUD + 状态机 + DTO 映射

## 测试用例说明

这些测试用例基于 mall 项目的真实代码结构设计，使用 fixture 代码片段（不依赖克隆仓库）。
每个用例描述了一个真实的企业级代码变更任务，包含：
- 输入：自然语言变更描述 + 当前代码 fixture
- 期望 AIU 类型：代码变更涉及的 AIU 操作列表
- 期望影响文件：需要修改的文件路径列表
- 记忆主题：应该从记忆库中检索的相关知识点

## 技术栈
- Java 11 / Spring Boot 2.x
- MyBatis + MyBatis Generator
- MySQL（订单状态机使用 status 枚举字段）
- Swagger/SpringDoc（API 文档）
