# Langfuse 真实模型验收记录（2026-10-23）

## 本次执行范围

实际调用项目配置的 DeepSeek 模型，使用生产 Agent 工厂、任务编排、Skills、审查及 HITL。ERP 使用进程内合成数据，检查点、记忆及工作区使用测试实现，不向真实 ERP 下单。36 条业务用例为 12 类场景、每类 3 个变体，不是 36 个独立业务类型。

另外启动了真实 FastAPI 后端、MongoDB 与 Docker，完成 HTTP 流式对话冒烟；之后启动 MCP 服务并验证加载 23 个工具，再次完成 HTTP 冒烟。HTTP 冒烟与下表业务测试是不同测试路径，不能合称 36 次 HTTP 全链路验收。HTTP 冒烟只检查传输结束和错误事件，不作为业务语义正确率。

## 实测结果

| 指标 | 结果 |
| --- | --- |
| 业务断言通过 | 36/36（本次有限合成集内 100%） |
| 真实模型响应数 | 136 |
| 输入 Token | 1,094,492 |
| 输出 Token | 30,267 |
| 未返回用量的模型响应 | 0 |
| 单用例耗时 P95（最近秩） | 18.403 秒 |
| 审批前写入尝试 | 0 |
| 云端核对到的本轮业务 Trace | 36/36 |
| 云端 task_acceptance 评分 | 36 |
| 云端 observation / generation | 1,896 / 136 |

逐条读取云端 observation，确认 input/output 均为空，符合元数据上传策略。示例：[查看本轮真实调用 Trace](https://us.cloud.langfuse.com/project/cmvkwfdsz008cad0j8ussq2w8/traces/e1521938e931fcb472a04cc9a4a639fa)。需登录对应项目。

耗时包含 Agent 构建及多步执行，不是单次模型响应延迟；基础组和扩展组曾并行运行，不是受控性能基准。Token 是模型返回的用量，不是价格计算，也不能据此声称成本降低。没有为了提高通过率重跑失败样本；预先额外运行过 1 条冒烟，不计入上述 36 条。

原始数据位于 `evals/business/results/langfuse-live-base-20261023/` 和 `langfuse-live-extended-20261023/`，含数据集、代码指纹、模型配置、逐条断言、耗时、用量及 trace_id。云端核对结果由 `python -m evals.verify_live_langfuse` 保存到 `evals/business/results/langfuse-live-report-20261023.json`。

## 在 Langfuse 查看

查看名称为 `erp.request` 的 Trace，按 metadata 中 `evaluation=true`、`historical_import=false` 筛选本次真实执行；`case_id` 对应本地结果。`task_acceptance` 为总体业务评分，其余分数为各验收断言。历史导入名为 `eval.historical`，不要混入本次统计。真实执行仍只上传元数据，不上传对话或订单正文。

## 发现的限制

- Docker 自定义 seccomp 配置启动失败，现有逻辑回退到基础沙箱。本次不构成安全隔离验证，也不构成故障恢复验收。
- 首批 HTTP 冒烟时 MCP 尚未启动，服务降级为无 ERP 工具；随后启动 MCP，确认工具加载后另做 HTTP 冒烟。没有调用真实 ERP 的读写接口验收。
- 路由模型对比本次未重新运行，之前导入的 800 条记录仍属于历史评测。

## 简历建议

接入 Langfuse 实现 Agent 执行链路追踪、模型 Token 用量统计及自动验收评分；在真实模型与模拟 ERP 环境下运行覆盖 12 类场景的 36 条业务用例，本轮验收通过 36/36，记录 136 次模型响应，测试中未发生审批前写入。

以上是测试结果，不是线上 SLA，也不是泛化到所有业务任务的成功率。
