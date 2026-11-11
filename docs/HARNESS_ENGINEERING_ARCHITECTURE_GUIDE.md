# ERP 智能采购助手：Harness Engineering 架构学习指南

> 本文面向第一次系统学习 Agent Harness 的开发者。内容以仓库当前源码为准，重点解释一次请求如何被规划、执行、审查、中断、恢复和持久化，而不是简单复述项目 README。
>
> 阅读前置：能阅读 Python、TypeScript，了解大语言模型的基本调用方式即可。LangGraph、MCP、SSE 等概念会在使用处解释。

## 目录

- [1. 什么是 Harness Engineering](#1-什么是-harness-engineering)
- [2. 项目整体架构](#2-项目整体架构)
- [3. 一次业务请求的完整生命周期](#3-一次业务请求的完整生命周期)
- [4. Harness 核心：状态、阶段与计划](#4-harness-核心状态阶段与计划)
- [5. Review：从路由到有限重做](#5-review从路由到有限重做)
- [6. HITL：中断与恢复](#6-hitl中断与恢复)
- [7. 主 Agent 的组装过程](#7-主-agent-的组装过程)
- [8. Harness 周边工程能力](#8-harness-周边工程能力)
- [9. SSE 协议与前端状态映射](#9-sse-协议与前端状态映射)
- [10. 持久化、隔离与并发模型](#10-持久化隔离与并发模型)
- [11. 可观测性、测试与评测](#11-可观测性测试与评测)
- [12. 推荐源码阅读顺序](#12-推荐源码阅读顺序)
- [13. 渐进式学习练习](#13-渐进式学习练习)
- [14. 当前实现边界与改进方向](#14-当前实现边界与改进方向)
- [15. 最终心智模型](#15-最终心智模型)

---

## 1. 什么是 Harness Engineering

### 1.1 从“调用模型”到“约束模型”

最简单的 LLM 应用通常只有一条路径：

~~~text
用户输入 → 拼接 Prompt → 调用模型 → 返回文本
~~~

这种方式可以演示能力，但很难直接承担真实业务：

- 模型可能忘记调用业务系统，直接编造结果；
- 多步骤任务没有可观察的计划和进度；
- 写操作可能缺少参数校验或用户授权；
- 工具失败后，模型可能仍声称任务已经完成；
- 请求中断后无法从原位置恢复；
- 不同用户可能共享临时文件、记忆或运行状态；
- 出错时无法判断是模型、工具、沙箱还是业务服务的问题。

Harness Engineering 的核心不是“换一个更强的 Prompt”，而是在模型外部建立一套工程控制层。这个控制层负责：

1. 定义模型可以看到什么上下文；
2. 定义模型可以调用哪些工具；
3. 记录任务计划和执行状态；
4. 隔离代码和文件操作；
5. 在高风险操作前暂停并等待人工决策；
6. 对结果进行独立审查；
7. 限制模型调用和工具调用次数；
8. 持久化执行状态，使任务可以恢复和审计；
9. 用测试与评测验证整个系统，而不只测试单个函数。

因此，可以把本项目中的 Harness 理解为：

> 以 DeepAgent/LangGraph 为运行内核，以中间件、结构化状态、工具权限、Rubric 评审、HITL、沙箱、记忆和持久化为控制面的 Agent 工程系统。

### 1.2 本项目解决的五类问题

| 工程问题 | 项目中的解决方式 |
|---|---|
| 模型如何执行复杂任务 | Todo/Plan、工具调用、子 Agent 委派 |
| 如何判断结果是否可信 | 混合 Review 路由、Rubric Grader、执行证据升级 |
| 如何控制副作用 | Docker 沙箱、工具白名单、HITL、写操作禁止自动重放 |
| 如何跨轮延续状态 | LangGraph Checkpointer、HOT/WARM/COLD 记忆 |
| 如何观察和验证运行 | SSE 阶段事件、Harness Trace、Langfuse、单元测试与业务评测 |

---

## 2. 项目整体架构

### 2.1 系统组件分层图

~~~mermaid
flowchart TB
    U["用户"]

    subgraph FE["Frontend · Next.js / React"]
        UI["聊天界面"]
        HOOK["useChat + useSSE"]
        HITLUI["审批卡片 / 信息补充表单"]
    end

    subgraph API["Backend API · FastAPI"]
        CHAT["chat.py<br/>SSE 流、中断与恢复"]
        LOADER["AgentLoader<br/>用户级 Agent Session"]
        HISTORY["history.py<br/>会话历史"]
    end

    subgraph CORE["Agent Core · DeepAgent / LangGraph"]
        GRAPH["Compiled State Graph"]
        HARNESS["Harness 中间件<br/>Phase / Review / Limits"]
        SUB["采购分析 / 订单子 Agent"]
        SKILL["渐进式 Skills"]
    end

    subgraph EXEC["Execution Plane"]
        MCPCLIENT["MCP Client"]
        SANDBOX["Docker Sandbox<br/>或 LocalShell 降级"]
        CUSTOM["图表、文档、搜索、记忆等自定义工具"]
    end

    subgraph ERPBRIDGE["ERP Bridge"]
        MCPSERVER["FastMCP Server"]
        ERP["Java ERP REST API"]
    end

    subgraph DATA["State & Data"]
        CHECKPOINT["MongoDBSaver<br/>图执行状态"]
        STORE["MongoDBStore<br/>记忆与持久化 Skills"]
        DISPLAY["conversations / display_messages<br/>harness_traces"]
    end

    OBS["Langfuse<br/>可选、元数据遥测"]

    U --> UI
    UI --> HOOK
    HOOK -->|"HTTP + SSE"| CHAT
    HITLUI -->|"resume"| CHAT
    CHAT --> LOADER
    LOADER --> GRAPH
    GRAPH <--> HARNESS
    GRAPH --> SUB
    GRAPH --> SKILL
    GRAPH --> MCPCLIENT
    GRAPH --> SANDBOX
    GRAPH --> CUSTOM
    MCPCLIENT -->|"SSE transport"| MCPSERVER
    MCPSERVER -->|"HTTP REST"| ERP
    GRAPH <--> CHECKPOINT
    GRAPH <--> STORE
    CHAT <--> DISPLAY
    CHAT -. "metadata only" .-> OBS
~~~

### 2.2 各层职责

#### 前端层

前端不负责业务推理，只负责：

- 发送聊天和恢复请求；
- 逐块解析 SSE；
- 展示模型文本、工具调用、Todo 和 Harness 阶段；
- 收集中断所需的审批或补充信息；
- 加载和删除历史会话。

关键入口：

- `frontend/src/hooks/useChat.ts`
- `frontend/src/hooks/useSSE.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`

#### API 编排层

FastAPI 将 Agent 图包装成适合 Web 客户端消费的协议：

- 把 HTTP 请求转成 LangGraph 输入；
- 使用 `messages`、`values`、`custom` 三种流读取运行过程；
- 把图状态转换成 SSE 事件；
- 检测中断并保存展示状态；
- 使用 `Command(resume=...)` 恢复原图；
- 管理用户级 Agent、锁、沙箱租约和运行时上下文。

关键入口：

- `src/api_view/api/chat.py`
- `src/api_view/agent_loader.py`
- `src/api_view/web_main.py`

#### Agent 控制层

这是 Harness 的核心。它不直接保存 UI 消息，而是控制一次 Agent 运行：

- 创建模型、工具、Backend、子 Agent 和中间件；
- 扩展 LangGraph State；
- 决定是否开启独立评审；
- 根据工具执行证据升级评审；
- 管理沙箱健康、技能加载和记忆注入；
- 限制模型及工具调用次数。

关键入口：

- `src/agent/main_agent.py`
- `src/agent/harness.py`
- `src/agent/review_policy.py`
- `src/agent/middlewares/review_gate.py`

#### 业务接入层

MCP Server 将 Agent 工具协议和真实 ERP REST API 解耦：

~~~text
Agent 工具调用 → MCP Client → FastMCP Tool → ERPHttpClient → Java ERP
~~~

Agent 只依赖工具名和 Schema，不需要知道 ERP 的具体 URL、HTTP 方法和响应细节。

---

## 3. 一次业务请求的完整生命周期

下面以“分析库存并给出采购建议”一类需要工具和评审的请求为例。

### 3.1 完整时序

~~~mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant UI as useChat
    participant API as FastAPI chat.py
    participant Loader as AgentLoader
    participant Graph as DeepAgent Graph
    participant Harness as Harness Middleware
    participant Tool as MCP / Sandbox / Custom Tool
    participant Grader as Rubric Grader
    participant Mongo as MongoDB

    User->>UI: 输入业务请求
    UI->>API: POST /api/chat/stream
    API->>Loader: get_session(user_id)
    Loader-->>API: 用户独享 AgentSession
    API->>API: 获取 run_lock、沙箱 lease、绑定 ContextVar
    API-->>UI: thinking:start
    API->>Graph: astream(messages, config)
    Graph->>Harness: before_agent
    Harness->>Harness: ReviewPolicy 路由
    Harness-->>Graph: phase=planning + rubric/decision
    Graph-->>API: values: phase / review_decision
    API-->>UI: phase / todo_update
    Graph->>Graph: 模型规划并选择工具
    Harness-->>Graph: after_model → phase=executing
    Graph->>Tool: 调用业务工具或委派子 Agent
    Tool-->>Graph: 工具结果
    Graph-->>API: messages: tool_start/result/token
    API-->>UI: 对应 SSE 事件
    Graph->>Harness: after_agent 执行证据检查
    Harness->>Grader: 有 rubric 时执行结构化评审
    Grader-->>Graph: satisfied / needs_revision / failed
    alt needs_revision 且允许重做
        Graph->>Graph: 跳回 model 修正
    else 通过、失败或达到上限
        Harness-->>Graph: phase=result + review_result
    end
    Graph-->>API: custom/values/messages 流
    API->>Mongo: 保存展示消息与 Harness Trace
    Graph->>Mongo: Checkpoint / Store 持久化
    API-->>UI: done
    API->>API: 释放 ContextVar、lease 和 run_lock
~~~

### 3.2 第一步：前端发送请求

`useChat.ts` 的 `doSend()`：

1. 创建用户消息；
2. 设置 `streaming=true`；
3. 调用 `streamChat()`；
4. 将 `thread_id`、`user_id`、`username` 和消息传给后端。

`useSSE.ts` 使用 `AbortController` 管理正在进行的请求，并把网络数据块交给 `SSEParser`。每个解析出的事件再由 `useChat.handleEvent()` 更新前端状态。

### 3.3 第二步：获得用户级 AgentSession

`AgentLoader.get_session(user_id, username)` 采用两层资源模型：

- MongoDB Store 和 Checkpointer 是进程内共享资源；
- Agent 实例、稳定沙箱 Proxy 和 `run_lock` 按用户创建。

`AgentSession` 包含：

| 字段 | 作用 |
|---|---|
| `user_id` / `username` | 用户身份 |
| `agent` | 已编译的 DeepAgent 图 |
| `run_lock` | 串行化同一用户的运行 |

这避免了不同用户共享有状态中间件或沙箱引用。构建锁 `_session_build_locks` 还可防止并发请求为同一个用户重复创建 Agent。

### 3.4 第三步：绑定运行上下文

在调用图之前，`stream_chat_response()` 会：

1. 获取用户的 `run_lock`；
2. 从 `SandboxManager` 获取运行 lease；
3. 用 ContextVar 绑定当前用户对应的沙箱；
4. 绑定当前 `user_id` 和共享 Store；
5. 调用 `session.agent.astream()`。

这些 ContextVar 使图表、文档、记忆和技能工具不必通过全局可变变量猜测“当前用户是谁”。

### 3.5 第四步：同时读取三类 LangGraph 流

实际代码使用：

~~~python
stream_mode=["messages", "values", "custom"]
subgraphs=True
~~~

| 流类型 | 主要内容 | Web 层用途 |
|---|---|---|
| `messages` | 模型 token、ToolMessage、子图消息 | 输出文本及工具调用过程 |
| `values` | 当前完整图状态 | 读取 phase、todos、review_decision 和中断 |
| `custom` | 中间件主动发出的结构化事件 | 展示 Grader 开始、结束与 review_result |

`subgraphs=True` 使子 Agent 的消息也进入流。Web 层通过 namespace 中是否包含 `analyst` 或 `order`，把文本来源标记为对应子 Agent。

### 3.6 第五步：模型执行工具或委派子 Agent

模型可以：

- 直接调用 MCP 工具读取或修改 ERP；
- 使用 Docker 沙箱执行文件和代码任务；
- 调用图表、文档、联网搜索等自定义工具；
- 调用 `task` 委派给采购分析或订单子 Agent；
- 使用 `write_todos` 等框架能力管理计划。

工具调用不是最终答案之外的隐藏细节。`chat.py` 会把工具开始、增量参数、结果和结束转换成 SSE，前端可以实时展示。

### 3.7 第六步：Review 与有限修正

入口路由认为任务需要审查时，State 中会出现 `rubric`。Agent 执行结束后，Rubric Grader 根据对话和工具执行记录给出结构化结论：

- `satisfied`：满足标准；
- `needs_revision`：允许时返回模型修正；
- `failed`：审查失败；
- `max_iterations_reached`：超过审查迭代上限；
- `grader_error`：评审器异常。

即使入口决定跳过，工具错误、多工具调用、多来源或写操作等执行信号也可能在结束前把本轮升级为需要 Review。

### 3.8 第七步：保存并清理

正常结束或中断时，Web 层保存：

- 前端展示消息；
- Harness 阶段与 Review Trace；
- 会话标题和更新时间。

LangGraph 自己通过 Checkpointer 保存图状态。最后无论成功还是异常，`finally` 都会释放运行时绑定、沙箱 lease 和用户锁。

---

## 4. Harness 核心：状态、阶段与计划

### 4.1 四阶段不是四个硬编码节点

项目对外展示：

~~~text
Planning → Executing → Review → Result
~~~

但源码里没有手写四个固定 LangGraph 节点并按直线连接。阶段由 `HarnessPhaseMiddleware` 在不同生命周期钩子中写入图状态：

| 钩子 | 写入逻辑 |
|---|---|
| `before_agent` | 本轮开始，写 `phase=planning`，同时进行 Review 路由 |
| `after_model` | 模型产生工具调用时，写 `phase=executing` |
| Rubric custom event | Grader 开始时，Web 层发射 `reviewing` |
| `after_agent` | 构造 `review_result`，最终写 `result`；需要修正时可标记 `reviewing` |

因此更准确的表述是：

> 四阶段是由中间件依据图运行事件维护的结构化状态投影，用于可观测、持久化和前端展示；真正的执行图仍由 DeepAgent 的模型、工具、子图和中间件回路组成。

理解这个区别很重要。阶段条是对复杂运行过程的抽象，不等于底层只执行四个步骤。

### 4.2 HarnessPhaseState

`HarnessPhaseState` 继承 LangChain 的 `AgentState`，增加：

| 字段 | 可见性 | 含义 |
|---|---|---|
| `phase` | 公共状态 | 当前 Harness 阶段 |
| `plan` | 公共状态 | Todo 转换后的结构化计划 |
| `review_result` | 公共状态 | 最终结构化评审结果 |
| `review_decision` | 公共状态 | 是否评审、来源、任务类型、检查项 |
| `_harness_rubric_source` | 私有状态 | 标识 rubric 是否由 Harness 自动注入 |
| `_review_start` | 私有状态 | 当前轮工具证据扫描起点 |
| `_review_write_attempted` | 私有状态 | 本轮是否尝试写操作 |
| `_review_signals` | 私有状态 | 工具错误、多来源等升级信号 |

私有字段使用 `PrivateStateAttr`，属于图内部控制数据，不应被当作业务响应。

### 4.3 Todo 与 Plan 的关系

Todo 来自 DeepAgent 内置的 TodoList 能力，典型形态为：

~~~json
[
  {"content": "查询库存预警", "status": "completed"},
  {"content": "分析缺货风险", "status": "in_progress"}
]
~~~

`_build_plan_from_todos()` 将其转换为 Pydantic `Plan`：

- 为步骤生成 `step-0`、`step-1` 等 ID；
- 保留 `pending / in_progress / completed`；
- 记录当前步骤；
- 生成 `created_at`。

这里的 Plan 是 Todo 的结构化快照，不是另一个独立规划引擎。`PlanStep.result` 已在 Schema 中预留，但当前转换逻辑没有回填步骤结果摘要。

### 4.4 YAML DSL 的真实作用

`src/agent/harness_config.yaml` 声明：

- 阶段名称和展示标签；
- Review 模式与策略；
- 路由超时和最大评审迭代；
- 任务类型关键词；
- 各类任务的 Rubric；
- 可观测性开关。

需要注意：它是“部分声明式”而不是完整工作流 DSL。

- Rubric、任务关键词和部分参数确实由配置驱动；
- 阶段钩子、升级信号、跳转行为仍在 Python 中实现；
- 修改 YAML 后需要重启后端，当前没有热加载机制。

---

## 5. Review：从路由到有限重做

Review 是本项目最值得学习的 Harness 设计之一，因为它同时考虑了成本、可靠性和副作用安全。

### 5.1 Review 总流程

~~~mermaid
flowchart TD
    START["本轮请求进入 before_agent"] --> MODE{"review.mode"}
    MODE -->|"never"| SKIP["不注入自动 rubric"]
    MODE -->|"always"| REVIEW["进入 Review"]
    MODE -->|"auto"| RULE{"确定性规则能否判断"}

    RULE -->|"问候/感谢/单一概念"| SKIP
    RULE -->|"查询、分析、写操作等"| REVIEW
    RULE -->|"模糊请求"| ROUTER["DeepSeek 或 JEV 路由"]
    ROUTER -->|"review"| REVIEW
    ROUTER -->|"skip"| SKIP
    ROUTER -->|"uncertain / 超时 / 非法输出"| REVIEW

    SKIP --> EXEC["Agent 执行"]
    REVIEW --> RUBRIC["组合固定底线 + 任务 Rubric + checks"]
    RUBRIC --> EXEC

    EXEC --> SIGNAL{"执行证据是否需要升级"}
    SIGNAL -->|"否"| GATE{"State 中是否有 rubric"}
    SIGNAL -->|"工具错误/多工具/多来源/写操作/委派"| UPGRADE["升级 decision 并注入 rubric"]
    UPGRADE --> GATE

    GATE -->|"否"| RESULT["直接结束"]
    GATE -->|"是"| GRADER["Rubric Grader"]
    GRADER -->|"satisfied / failed"| RESULT
    GRADER -->|"needs_revision 且只读"| RETRY{"是否达到迭代上限"}
    RETRY -->|"否"| EXEC
    RETRY -->|"是"| RESULT
    GRADER -->|"本轮尝试写操作"| ONCE["只允许单轮评审，不自动重放写操作"]
    ONCE --> RESULT
~~~

### 5.2 三种 Review 模式

| 模式 | 行为 |
|---|---|
| `auto` | 默认模式。简单对话跳过，业务任务按规则或模型判断 |
| `always` | 有用户输入就审查 |
| `never` | 关闭自动评审，但不会关闭 HITL；显式传入 rubric 仍可保留 |

### 5.3 Hybrid 路由

`ReviewPolicy.rule()` 先处理低成本、确定性场景：

- 明确要求复核或高风险业务动作：审查；
- 独立问候、感谢：跳过；
- 单一概念定义：跳过；
- 查询、搜索、统计、分析、比较、生成、导出：审查。

无法明确判断时，调用结构化路由模型。路由结果 `ReviewRoute` 包含：

~~~text
decision: skip | review | uncertain
task_type: default | analysis | order | inventory | supplier
reason: 简短原因
checks: calculation | sources | constraints | comparison | artifact
~~~

路由模型只负责选择控制策略，不回答业务问题，也不执行工具。`chat.py` 还会过滤带有 `review_router` tag 的模型输出，防止内部控制内容被流式发送给用户。

### 5.4 Fail-closed 降级

如果路由：

- 超时；
- 返回不符合 Schema 的内容；
- API 不可用；
- 给出 `uncertain`；

系统会保守进入 Review，而不是默认放行。这是典型的 fail-closed 策略：控制组件失败时选择更安全的路径。

### 5.5 Rubric 的组成

`compose_rubric()` 将三部分拼接：

1. 固定业务底线，例如不编造工具成功、写操作必须经过审批；
2. `harness_config.yaml` 中与任务类型匹配的 Rubric；
3. 路由模型从白名单中选择的附加检查项。

路由模型不能自由改写固定底线，只能选择预定义检查项。这比让另一个模型任意生成评审标准更容易控制。

### 5.6 执行证据升级

入口路由只能看到请求、计划和历史摘要，无法预知工具实际执行情况。`ReviewExecutionGate` 因此在执行后扫描本轮消息：

- 工具返回错误；
- 工具调用数量达到阈值；
- 使用多个查询/搜索来源；
- 调用了 create、update、delete、inbound、outbound 等写入或执行类工具；
- 使用 `task` 委派子 Agent。

若入口曾跳过 Review，但出现上述信号，系统会注入 rubric 并把 `review_decision.source` 改为 `execution`。

`_review_start` 保证只扫描当前轮，避免上一轮的工具错误污染新请求。

### 5.7 为什么写操作不能自动重做

假设模型创建订单后，Grader 判断回答格式不完整。如果系统简单地把整轮跳回模型，模型可能再次调用 `order_create`，造成重复订单。

`SafeRubricMiddleware` 的处理方式：

- 只读任务：允许 RubricMiddleware 在上限内要求模型修正；
- 本轮发生写入尝试：切换到 `max_iterations=1` 的评审器；
- 子 Agent 委派也保守视为可能包含隐藏写操作。

这解决的是“评审回路不应重放副作用”，但不等于业务系统已经具备幂等性。真正生产环境仍应为订单创建提供幂等键、唯一约束或请求去重。

### 5.8 中间件顺序为何重要

`ReviewExecutionGate` 注册在 `SafeRubricMiddleware` 之后。项目依赖 after-agent 钩子的逆序执行，使 Gate 先把执行信号写入 State，Rubric 再根据最新状态决定是否评审以及是否禁用重放。

这说明 Harness 中间件不是一组可随意排序的插件。它们之间存在控制流依赖，修改顺序必须配套回归测试。

---

## 6. HITL：中断与恢复

HITL（Human in the Loop）用于让人类参与高风险决策或补齐缺失信息。

### 6.1 两类中断

#### 工具审批中断

主 Agent 的 `INTERRUPT_ON_TOOLS` 至少保护：

- `order_create`
- `order_update`

订单子 Agent 的 YAML 还为 `order_create`、`order_update` 和 `order_update_status` 声明了各自允许的决策。

#### 信息补充中断

`request_order_info` 校验订单字段。如果缺少订单号、明细、零部件 ID、数量或单价，则调用 LangGraph `interrupt()`，向前端发送当前已提取数据和缺失字段。

### 6.2 中断恢复时序

~~~mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant UI as 审批/补充信息组件
    participant API as chat.py
    participant Graph as LangGraph
    participant CP as MongoDB Checkpointer
    participant Tool as 受保护工具

    Graph->>CP: 保存中断点状态
    Graph-->>API: values.__interrupt__
    API-->>UI: SSE interrupt
    API->>API: 保存 display_messages 与 harness_trace
    API-->>UI: done(interrupted=true)

    User->>UI: 批准、拒绝、编辑或补充字段
    UI->>API: POST /api/chat/{thread_id}/resume
    API->>Graph: Command(resume=resume_data)
    Graph->>CP: 读取同一 thread_id 的 checkpoint

    alt 用户批准或补充完成
        Graph->>Tool: 从中断点继续
        Tool-->>Graph: 工具结果
        Graph-->>API: 后续流事件
    else 用户拒绝
        Graph-->>API: 生成拒绝后的结果
    end
~~~

### 6.3 为什么恢复不是“重新问一次模型”

恢复请求没有创建一条新的普通用户消息，而是：

~~~python
Command(resume=resume_data)
~~~

图通过同一个 `thread_id` 找到 checkpoint，从保存的中断位置继续。这使审批与原工具调用属于同一次逻辑执行，避免重新解析整段对话并猜测上次做到哪里。

---

## 7. 主 Agent 的组装过程

`create_main_agent()` 是理解项目依赖关系的最佳入口。源码把过程划分为七个主要步骤。

### 7.1 第 1 步：创建模型

项目分别创建：

- 主模型：允许思考，用于对话和工具选择；
- Grader 模型：`thinking=False`，用于结构化评审；
- Review Router：由配置选择 DeepSeek 或 JEV。

Router、主模型和 Grader 承担不同职责，不应把它们视为一次统一模型调用。

### 7.2 第 2 步：创建 CompositeBackend

默认 Backend 是用户的执行沙箱；部分虚拟路径路由到 Store：

| 路径 | Backend | 作用 |
|---|---|---|
| 默认路径 | Docker Sandbox 或 LocalShell | 文件与命令执行 |
| `/memories/` | `StoreBackend` | 用户记忆文件视图 |
| `/persisted-skills/` | `StoreBackend` | 用户持久化 Skills |

这是 CompositeBackend 的价值：模型看到统一文件接口，Harness 根据路径把操作分发到不同存储。

### 7.3 第 3 步：加载工具

工具来源包括：

- MCP Server 动态返回的 ERP 工具；
- 图表、文档、搜索、抓取、下载、HITL 等自定义工具；
- 可选的 `read_memory` 和 `remember`；
- `list_skills`、`read_skill`、`read_skill_resource` 等技能读取工具；
- DeepAgent 框架提供的文件、执行、Todo 和委派能力。

工具总数是运行时动态值，取决于：

- MCP Server 是否可达；
- 记忆工具开关；
- 当前框架版本；
- Skills 读取工具；
- 子 Agent 的实际工具匹配结果。

因此不应把 README 中某个固定工具数量当作永久架构约束。

### 7.4 第 4 步：加载子 Agent

`subagents/loader.py` 读取 YAML，完成：

- 必填字段校验；
- 工具名到实际 Tool 对象的解析；
- `interrupt_on` 解析；
- 输出契约提示词构造；
- 委派上下文协议生成。

当前包含：

| 子 Agent | 主要职责 | 权限特点 |
|---|---|---|
| `procurement-analyst` | 供应商、零部件、库存和订单分析 | 以读取、统计、图表和搜索为主 |
| `procurement-order` | 订单创建、修改、状态跟踪 | 拥有写工具，并配置 HITL |

工具匹配顺序是：精确名称 → `pattern_` 前缀 → 子串兜底。前两层用于减少意外的权限扩大。

### 7.5 第 5 步：组装中间件

下表按 `main_agent.py` 中的注册顺序列出主要中间件：

| 顺序 | 中间件 | 核心职责 |
|---:|---|---|
| 1 | `SandboxHealthMiddleware` | 请求前检查沙箱，故障时重建并热替换 |
| 2 | `HarnessPhaseMiddleware` | Phase、Review 路由、Plan 和 ReviewResult |
| 3 | `ContextInjectionMiddleware` | 注入用户身份和偏好上下文 |
| 4 | `WarmMemoryMiddleware` | 每次模型调用动态加载 WARM 摘要 |
| 5 | `ProgressiveSkillsMiddleware` | 动态注入技能元数据目录 |
| 6 | `SkillsSyncMiddleware` | 把内置 Skills 增量同步到沙箱 |
| 7 | `UserSkillsRestoreMiddleware` | 恢复用户持久化 Skills |
| 8 | `ToolsSummarizationMiddleware` | 监控工具调用摘要 |
| 9 | `MemoryUpdateMiddleware` | 从本轮提取并合并用户偏好 |
| 10 | `MemoryConsolidationMiddleware` | 归档情节并触发遗忘扫描 |
| 11 | `SandboxCircuitBreakerMiddleware` | 对沙箱工具失败执行熔断 |
| 12 | `SafeRubricMiddleware` | 结构化评审；写操作只评一次 |
| 13 | `ReviewExecutionGate` | 根据执行证据升级 Review |
| 14 | `ModelCallLimitMiddleware` | 限制单次运行模型调用 |
| 15 | `ToolCallLimitMiddleware` | 限制单次运行工具调用 |

此外，`create_deep_agent()` 还会提供文件系统、Todo、子 Agent、对话摘要等框架能力。具体内置项应以当前安装的 DeepAgent 版本为准。

### 7.6 第 6 步：构建系统提示词

系统提示词由以下部分组合：

- 采购助手基本角色；
- 用户身份；
- WARM 记忆占位符；
- 记忆工具使用规则；
- 子 Agent 委派协议；
- Skills 动态目录占位符；
- `memory/AGENTS.md` 中的全局操作手册。

WARM 记忆和 Skills 目录不是只在 Agent 创建时固化一次，而是在模型调用时由中间件动态替换。

### 7.7 第 7 步：创建图

最终将模型、工具、提示词、中间件、子 Agent、Backend、HITL 配置、Checkpointer 和 Store 一次性传给 `create_deep_agent()`，得到可执行的 Compiled State Graph。

---

## 8. Harness 周边工程能力

### 8.1 MCP：隔离 Agent 与 ERP

MCP Server 注册供应商、零部件、订单和库存工具，再通过统一 HTTP Client 调用 ERP。

这种结构带来三个好处：

1. Agent 不依赖 ERP 内部实现；
2. 工具 Schema 可以作为稳定契约；
3. MCP 不可用时，客户端可以降级为空工具列表，基础对话仍有机会工作。

但“连接失败返回空列表”也意味着业务任务可能直到运行时才发现缺少 ERP 能力，因此生产环境应增加启动健康检查和就绪探针。

### 8.2 子 Agent：按职责缩小上下文和权限

子 Agent 的价值不只是换一段 Prompt，而是：

- 为特定任务提供更聚焦的系统指令；
- 只暴露必要工具；
- 配置不同 HITL 策略；
- 约定主 Agent 传入的上下文；
- 约定返回结果的结构。

委派仍由主模型决定，因此 YAML 中的“触发词”主要是描述和提示，不是一个独立的硬编码路由器。

### 8.3 Docker 沙箱与稳定 Proxy

#### 沙箱生命周期

~~~mermaid
stateDiagram-v2
    [*] --> CREATE
    CREATE --> WARM: 创建预热容器
    WARM --> CLAIMED: 用户领取
    CLAIMED --> CACHED: 持久化容器映射
    CACHED --> CLAIMED: 从 MongoDB 恢复
    CLAIMED --> DESTROYED: 空闲超时或主动销毁
    CACHED --> DESTROYED: 不健康或失效
    DESTROYED --> CREATE: 重建
    WARM --> CREATE: 补充预热池
~~~

`SandboxManager` 管理用户到容器的映射、预热池、MongoDB 缓存、空闲清理、健康检查和 lease。

#### 为什么需要 SandboxBackendProxy

Agent、CompositeBackend 和工具在创建时会持有 Backend 引用。如果容器故障后直接创建一个新 Backend，旧对象仍会指向失效容器。

`SandboxBackendProxy` 提供稳定引用：

~~~text
Agent / Tool → Stable Proxy → 当前真实 Sandbox
                                  ↑
                              可热替换
~~~

健康中间件重建容器后，只替换 Proxy 内部 Backend。已有 Agent 和工具无需全部重建。

#### 重建后的再水合

新容器不仅要“能运行”，还要恢复工作环境。回调会：

1. 创建工作目录；
2. 上传项目副本；
3. 恢复内置 Skills；
4. 失效同步缓存；
5. 恢复用户 Skills。

这体现了 Harness 的恢复目标：不仅恢复计算资源，还恢复 Agent 所依赖的上下文和能力。

### 8.4 Skills 渐进披露

如果把所有 `SKILL.md` 全部塞进系统提示词，会快速消耗上下文窗口。项目改用三层读取：

1. `list_skills`：只暴露技能 ID、名称、描述和来源；
2. `read_skill(skill_id)`：选中后读取完整技能正文；
3. `read_skill_resource(skill_id, path)`：仅按正文需要读取具体资源。

`ProgressiveSkillsMiddleware` 在每次模型调用时刷新元数据目录，支持新安装、更新或删除后被当前 Agent 看到。

内置 Skills 来自仓库目录；用户 Skills 存入 `("persisted-skills", user_id)` 对应的 Store 命名空间，并在沙箱重建后恢复。读取逻辑还限制路径穿越、符号链接逃逸、秘密文件和超大文档。

### 8.5 HOT / WARM / COLD 三层记忆

~~~mermaid
flowchart LR
    MSG["当前会话消息 / Tool 结果 / Todos"] --> HOT["HOT<br/>LangGraph State + Checkpointer"]

    HOT -->|"after_agent 提取偏好"| SEM["Semantic Memory"]
    HOT -->|"会话归档"| EPI["Episodic Memory"]
    SEM --> WARM["WARM Brief<br/>稳定偏好 + 近期情节"]
    EPI -->|"近期窗口"| WARM
    WARM -->|"每次 model call 动态注入"| MODEL["Model Context"]

    SEM --> COLD["COLD Store"]
    EPI -->|"超过 WARM 天数"| COLD
    PROC["Procedural Memory"] --> COLD
    COLD -->|"read_memory / BM25 排序"| MODEL

    COLD -->|"TTL、数量上限、失效历史清理"| FORGET["Forget / Consolidate"]
~~~

三层是访问模式和上下文策略，不是三个独立数据库：

| 层 | 内容 | 读取方式 |
|---|---|---|
| HOT | 当前会话、工具结果、Todo | 图运行直接访问 |
| WARM | 有效语义记忆、近期情节摘要 | 每次模型调用自动注入 |
| COLD | 长期情节、程序经验、历史记录 | 工具按需检索 |

主要命名空间：

~~~text
("memories", user_id, "semantic")
("memories", user_id, "episodic")
("memories", user_id, "procedural")
("user-preferences", user_id)            # 兼容投影
("persisted-skills", user_id)             # 用户 Skills
~~~

`MemoryKeeper` 是新记忆逻辑的统一读写入口，负责语义冲突失效、情节幂等归档、检索排序、访问计数和遗忘。

### 8.6 元数据可观测性

`observability.py` 提供可选 Langfuse 集成：

- 默认关闭；
- 缺少必要 Key 时不启用；
- 用户与会话标识经过伪匿名化；
- 只发送运行元数据、耗时、状态和可获得的 Token usage；
- 不把 SSE 正文或回调 payload 发送到 Langfuse；
- 遥测失败不应破坏业务流程。

这类设计体现了“可观测性是旁路能力”：它能观察主链路，但不能成为主链路的单点故障。

---

## 9. SSE 协议与前端状态映射

### 9.1 后端事件

`chat.py` 当前可能发出：

| SSE event | 主要字段 | 来源 |
|---|---|---|
| `thinking` | `status=start/end` | Web 层 |
| `phase` | `phase`、`label` | Harness State 或 Grader custom event |
| `todo_update` | `todos` 或兼容字段 | values 流 / ToolMessage |
| `token` | `content`、`source` | messages 流 |
| `tool_start` | `name`、`id` | tool_call_chunks |
| `tool_args` | `args` | tool_call_chunks |
| `tool_result` | `name`、`content` | ToolMessage |
| `tool_end` | `id` | ToolMessage |
| `interrupt` | 中断类型和业务数据 | values 中的 `__interrupt__` |
| `review_result` | verdict、criteria、iteration | custom 流 |
| `error` | `message` | Web 层异常处理 |
| `done` | `thread_id`、`interrupted` | Web 层 |

### 9.2 State、SSE 与 UI 的映射

~~~text
LangGraph State / Stream
        ↓  chat.py 适配
SSE event + JSON data
        ↓  SSEParser
前端 SSEEvent
        ↓  useChat.handleEvent
React state
        ↓
PhaseBar / TodoList / ToolCall / Message / Interrupt UI
~~~

### 9.3 一个需要修正的契约差异

后端会发送 `review_result` 和 `error`，但当前 `frontend/src/lib/types.ts` 的 `SSEEvent` 联合类型没有声明这两个事件，`useChat.handleEvent()` 也没有对应分支。

这不会影响后端保存 Harness Trace，但前端目前不会显式展示结构化评审结果和后端错误事件。建议将 SSE 协议定义为单一契约，并为前后端生成或共享类型。

### 9.4 阶段枚举差异

后端终态使用 `result`，前端 `SSEPhaseEvent` 和 `HarnessPhase` 使用 `done`。`useChat` 在收到 `done` 事件时主动把 UI 阶段改成 `done`，但收到后端 `phase=result` 时依赖了类型断言。

建议统一为同一枚举，或者明确区分：

- Harness 业务阶段：`planning/executing/reviewing/result`；
- 传输生命周期：`thinking/done/error/interrupted`。

---

## 10. 持久化、隔离与并发模型

### 10.1 四类持久化数据不要混淆

| 数据 | 存储机制 | 主要消费者 | 用途 |
|---|---|---|---|
| 图状态与中断点 | `MongoDBSaver` Checkpointer | LangGraph | 继续同一 thread 的执行 |
| 跨会话记忆与 Skills | `MongoDBStore` | 中间件、工具、Backend | 用户级长期数据 |
| `display_messages` | Web 层 MongoDB collection | 前端历史消息 | 还原 UI 展示 |
| `harness_traces` | Web 层 MongoDB collection | 审计与排障 | 阶段、路由和评审时间线 |

`conversations` collection 负责历史列表、标题、用户归属和更新时间。

删除会话时，当前 Web 层删除会话记录、展示消息和 Harness Trace。是否同时清理 LangGraph Checkpoint 需要单独确认和设计，不能假设三者天然联动。

### 10.2 用户隔离

项目通过多层机制隔离用户：

- `AgentLoader._sessions[user_id]`：用户独享 Agent；
- SandboxManager：用户到容器的映射；
- Store namespace：记忆和 Skills 包含 `user_id`；
- ContextVar：工具获取当前用户的沙箱和 Store 上下文；
- 会话记录保存 `user_id`；
- resume 前查询 thread 的归属用户。

### 10.3 并发策略

同一用户的所有会话共享一个 `run_lock`，因此串行执行。原因是同一个用户沙箱中的 `/tmp`、`/workspace` 和生成文件可能互相覆盖。

不同用户拥有独立 Agent、锁和沙箱，可以并发运行。

这是一种安全优先的并发模型，但有明确代价：

- 同一用户开启多个浏览器会话时会互相排队；
- AgentSession 存在进程内内存，横向扩容需要粘性路由或外部会话协调；
- `asyncio.Lock` 不能跨进程或跨机器协调；
- 沙箱 lease 的语义需要与多实例部署重新设计。

---

## 11. 可观测性、测试与评测

### 11.1 三个观察层次

| 层次 | 工具 | 适合回答的问题 |
|---|---|---|
| 用户可见 | SSE、PhaseBar、Todo、ToolCall | 当前任务正在做什么 |
| 应用审计 | `harness_traces`、日志 | 为什么进入 Review、在哪个阶段停止 |
| 跨请求遥测 | Langfuse | 延迟、Token、错误率和评测关联 |

### 11.2 关键测试入口

| 测试文件 | 覆盖重点 |
|---|---|
| `src/test/test_hybrid_review.py` | 混合路由、超时、升级、写操作防重放 |
| `src/test/test_chat_interrupts.py` | 新旧中断格式、信息补充和正常结束 |
| `src/test/test_sandbox_lifecycle.py` | Proxy 热替换、重建再水合、用户隔离 |
| `src/test/test_progressive_skills.py` | 渐进披露、资源边界、用户 Skills |
| `src/test/test_memory_layer.py` | 记忆合并、冲突、检索、遗忘 |
| `src/test/test_memory_integration.py` | 真实图下的线程与用户隔离 |
| `src/test/test_observability.py` | 元数据策略、失败降级、上下文隔离 |
| `src/test/test_business_eval.py` | 业务验收规则和证据要求 |

推荐先运行不依赖外部服务的核心回归：

~~~powershell
python -m unittest src.test.test_hybrid_review -v
python -m unittest src.test.test_chat_interrupts -v
python -m unittest src.test.test_progressive_skills -v
python -m unittest src.test.test_memory_integration -v
python -m unittest src.test.test_sandbox_lifecycle -v
~~~

### 11.3 单元测试与业务评测的区别

单元/集成测试回答：

- 某个路由是否按预期选择；
- 中断能否正确转换为 SSE；
- 沙箱替换后旧 Proxy 是否仍可工作；
- 记忆命名空间是否隔离。

`evals/` 下的业务评测回答：

- Agent 是否真的调用了正确工具；
- 正确数字是否有真实工具证据；
- 缺字段时是否先询问而不是写入；
- 用户拒绝后是否停止执行；
- 路由模型在冻结数据集上的质量如何。

Harness 工程必须同时拥有这两类验证：代码正确不代表 Agent 行为正确，单次演示成功也不代表控制组件可靠。

---

## 12. 推荐源码阅读顺序

### 第一遍：先建立请求主线

1. `frontend/src/hooks/useChat.ts`  
   看前端如何发送、排队、恢复和消费事件。

2. `src/api_view/api/chat.py`  
   看 HTTP 如何转换成图输入，以及三类流如何转换成 SSE。

3. `src/api_view/agent_loader.py`  
   看用户级 Agent、共享 Store、Checkpointer 和并发锁。

4. `src/agent/main_agent.py`  
   看所有组件如何组装到一张图里。

### 第二遍：理解 Harness 控制面

5. `src/agent/harness.py`  
   理解 State、Phase、Todo→Plan 和 ReviewResult。

6. `src/agent/review_policy.py`  
   理解入口规则、模型路由、fail-closed 和 rubric 组合。

7. `src/agent/middlewares/review_gate.py`  
   理解执行证据升级和写操作防重放。

8. `src/agent/harness_config.yaml`  
   对照代码理解哪些行为可以配置。

### 第三遍：理解执行隔离

9. `src/agent/backends/sandbox_manager.py`
10. `src/agent/backends/sandbox_proxy.py`
11. `src/agent/middlewares/sandbox_health.py`
12. `src/agent/middlewares/sandbox_breaker.py`

重点追踪“容器故障 → 重建 → Proxy 热替换 → Skills 和项目恢复”。

### 第四遍：理解能力扩展

13. `src/agent/subagents/loader.py` 与两个 YAML；
14. `src/agent/progressive_skills.py`；
15. `src/agent/memory/keeper.py`；
16. `src/mcp_server/server_main.py` 与 `tools/`。

### 第五遍：用测试反向理解设计

优先阅读 Hybrid Review、沙箱生命周期、渐进式 Skills 和 Memory Integration 测试。测试通常比注释更清楚地表达了系统必须维持的不变量。

---

## 13. 渐进式学习练习

### 练习 1：画出一条真实事件时间线

目标：理解 Web 层和图状态的关系。

1. 启动前后端；
2. 发送一个简单问候和一个库存分析请求；
3. 在浏览器 Network 中记录 SSE 顺序；
4. 对照 `chat.py` 标出每个事件来自 messages、values 还是 custom；
5. 比较简单请求为什么没有 Grader 事件。

### 练习 2：增加一种只读任务 Rubric

目标：理解 YAML 配置与 Python 控制逻辑的边界。

1. 在 `task_types` 增加新类型和关键词；
2. 添加对应 Rubric；
3. 编写测试验证 `detect_task_type()` 和 `ReviewPolicy`；
4. 验证是否无需修改图结构。

### 练习 3：验证执行证据升级

目标：理解“入口判断”和“执行后判断”的区别。

1. 构造入口路由返回 skip 的测试；
2. 在工具结果中模拟错误；
3. 验证 `ReviewExecutionGate` 把 decision 升级为 review；
4. 验证只扫描当前轮。

### 练习 4：观察 HITL checkpoint

目标：理解中断恢复不是重新执行。

1. 发起创建订单；
2. 在审批点停止；
3. 检查前端展示消息与图 State；
4. 使用同一 thread 恢复；
5. 验证审批前的步骤没有从头重复。

### 练习 5：让沙箱故障后自动恢复

目标：理解稳定 Proxy。

1. 使用测试替身创建初始 Sandbox；
2. 让健康检查失败；
3. 触发重建；
4. 验证旧 CompositeBackend 引用执行到了新 Sandbox；
5. 验证 Skills 被重新同步。

### 练习 6：实现前后端 SSE 契约一致

目标：理解协议工程。

1. 为前端补充 `review_result` 和 `error` 类型；
2. 在 UI 中展示评审摘要；
3. 统一 `result` 与 `done` 的语义；
4. 为 parser 和 `handleEvent` 添加测试。

---

## 14. 当前实现边界与改进方向

以下内容是基于源码的架构评审建议，不代表现有代码没有价值；它们说明从学习项目走向生产系统时还要补哪些工程环节。

### 14.1 工具与配置

- 工具数量和能力是动态的，启动日志和健康端点应暴露实际注册结果。
- MCP 连接失败会返回空工具列表，建议区分“允许降级的普通对话”和“必须拒绝的 ERP 任务”。
- YAML 是部分 DSL。若要真正支持“改流程不改代码”，需要进一步声明节点、跳转、重试和错误策略。
- 子 Agent 工具解析仍保留子串兜底，生产环境更适合严格的显式工具 ID。

### 14.2 沙箱安全

- Docker 不可用时会降级到 `LocalShellBackend(virtual_mode=True)`，其隔离和安全属性不能等同于 Docker 沙箱。
- 生产环境应允许配置为 fail-closed：需要执行能力的任务在 Docker 不可用时直接拒绝，而不是落到本机执行。
- 当前项目会把仓库副本上传进每个用户沙箱，需要评估启动耗时、磁盘成本和源代码暴露范围。
- 沙箱网络使用和依赖安装仍需结合部署环境增加出口控制、镜像签名和制品扫描。

### 14.3 副作用与一致性

- “写操作不自动重放”只保护 Agent Review 回路，不能替代 ERP 幂等。
- 订单创建、库存出入库等接口应增加业务幂等键和唯一约束。
- Review、Checkpoint、展示消息和业务写入不是同一个事务，异常时可能出现部分成功。
- 删除会话是否清理 Checkpoint、生成文件和沙箱数据，需要定义完整的数据生命周期。

### 14.4 性能与扩展

- `MongoDBStore` 的同步 I/O 可能在异步请求路径中阻塞事件循环；高并发下应审计并迁移到异步实现或线程池。
- 每用户一个内存 AgentSession 适合单进程部署；多实例需要分布式 session/lock/lease 方案。
- 同用户全局串行简单可靠，但会限制多会话并发；可进一步按 workspace 或 thread 设计隔离目录和锁粒度。
- 记忆检索当前有单类读取上限和应用层排序，规模增大后需要分页、索引或专用检索服务。

### 14.5 前端契约

- API Base URL 和用户 ID 当前硬编码在前端，应改为环境配置和真实认证上下文。
- 后端事件集合与 TypeScript 联合类型不完整一致。
- 后端 `result` 和前端 `done` 的阶段命名需要统一。
- 前端没有消费结构化 `review_result`，用户看不到 Grader 的明确结论。
- 当前来源识别依赖 namespace 字符串包含关系，可改为后端输出显式 agent/source 元数据。

### 14.6 Review 质量

- 关键词任务分类便于解释，但容易受同义词和上下文影响；冻结数据集评测应持续覆盖新增业务。
- Review Router 和 Grader 是两个额外模型环节，需要分别观察成本、延迟和失败率。
- `needs_revision` 回路应持续验证不会间接触发隐藏副作用。
- Rubric 检查工具证据的一致性仍依赖模型判断，高风险业务可增加确定性校验器。

### 14.7 文档与代码同步

- README 中的固定工具数量、框架内置能力和依赖版本可能随运行环境变化。
- 建议由测试或启动脚本生成实际能力清单，文档只描述分类和发现方式。
- 架构文档应在中间件顺序、SSE 事件或持久化模型变化时同步更新。

---

## 15. 最终心智模型

学习这个项目时，可以始终抓住下面这条主线：

~~~text
用户请求
  ↓
Web 协议层：HTTP → LangGraph 输入，Graph Stream → SSE
  ↓
用户级运行环境：AgentSession + Lock + Sandbox Lease + ContextVar
  ↓
Harness 入口控制：Phase + Review Routing + Context + Memory + Skills
  ↓
Agent 执行：模型规划、Todo、工具、MCP、沙箱、子 Agent
  ↓
Harness 出口控制：执行证据升级 + Rubric Grader + 防副作用重放
  ↓
中断恢复或最终结果
  ↓
Checkpoint、Store、展示消息、Trace 和遥测
~~~

这套架构最值得借鉴的不是某个具体框架 API，而是四个设计原则：

1. **把控制数据结构化**：阶段、计划、路由和评审结果进入 State，而不是只存在于自然语言中。
2. **把高风险行为放到模型之外约束**：工具权限、沙箱、HITL、调用上限和防重放由代码负责。
3. **把失败当作正常路径设计**：路由超时、工具错误、沙箱失效、遥测异常都有降级或恢复策略。
4. **把 Agent 当作系统测试**：不仅验证函数，还验证工具证据、审批行为、跨轮状态和业务结果。

如果只记住一句话：

> 模型负责提出和执行智能决策，Harness 负责让这些决策在可控、可恢复、可审查的工程边界内运行。
