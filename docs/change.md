#### 前端模型设置（轻量补充功能）

在现有问答界面增加模型设置入口，不新增页面，也不调整上述 P0 / P1 / P2 计划范围。用户可在前端填写 API Key、Base URL、模型名和请求超时时间，并测试模型是否可用；保存后的配置用于当前浏览器会话中的聊天请求。连接测试在超时后会主动结束并显示明确提示。前端配置为空时，继续使用后端 `.env` 中的默认模型配置。

#### 核心检索与可靠性修复（2026-07-17）

本轮修复聚焦于限定范围检索、引用可信度、索引一致性、中文检索和 PDF 导入边界，不改变现有产品主流程。

##### 限定范围混合检索

- 将 `allowed_paper_ids` 直接下推到 Chroma metadata `where`，避免先取全库 Top-N 再过滤导致勾选论文漏召回。
- BM25 在选定论文集合内选取 Top-K，不再被范围外的高分 chunk 挤占候选名额。
- 小范围检索会补充每篇论文的 fallback chunk，再按论文轮询截断；当论文数量大于 `top_k` 时优先保留相关性，避免按 `paper_id` 任意取舍。
- SQLite 范围取块改为窗口查询，限制每篇论文的候选数量，避免单篇长论文占满全局 `LIMIT`。

##### 引用与 evidence 对齐

- 多视角综述的每份局部笔记先保留自己的 `[n]`，合并 chunk 后统一映射为最终上下文编号。
- 返回回答前校验所有数字引用，移除越界 marker，同时保留 `[2024]` 这类年份表达。
- `citations` 只包含答案实际引用到的论文；`evidence[n-1]` 继续与回答中的 `[n]` 一一对应。
- 综述最终上下文会为每篇勾选论文补充至少一个可用 chunk，降低“要求覆盖全部论文但没有证据”的概率。

##### 索引一致性

- 在修改持久化数据前完成 chunk embedding，模型不可用时不会提前破坏旧索引。
- 替换单篇论文向量前保存 Chroma 快照；向量写入或 SQLite 提交失败时恢复旧向量。
- 论文元数据与 SQLite chunks 在同一事务内提交，并用索引写锁避免并发导入交叉覆盖快照。
- 每次成功提交后显式使 BM25 缓存失效，再按需重建；缓存读写增加锁，保证 BM25 实例与文档列表属于同一版本。
- 本地 MiniLM embedding 实例改为进程内复用，减少重复初始化 ONNX 模型的开销。

##### 中文检索与切分

- BM25 tokenizer 现在会规范化英文标点，并为连续 CJK 文本生成单字与双字 token。
- 普通中文库内问答会复用意图识别阶段生成的英文检索词，以改善中文问题对英文论文的召回。
- 使用本地 MiniLM 时，中文占比较高的文本会使用最多 220 字符、最多 40 字符 overlap 的分块，避免超过模型的 256 wordpiece 上限。
- 分隔符补充中文句号、问号、感叹号、分号和逗号。

##### PDF 与运行边界

- 本地 PDF 上传增加内容校验和大小限制，默认 `PDF_UPLOAD_MAX_BYTES=31457280`（30 MiB）。
- PDF 以分块方式读取，超过限制返回 HTTP 413；解析与建索引移到工作线程，避免阻塞 FastAPI 事件循环。
- PDF 解析或导入失败时删除暂存文件，避免遗留孤立上传文件。
- 默认 `APP_HOST` 从 `0.0.0.0` 调整为 `127.0.0.1`，符合本地单用户定位。

##### Embedding 初始化

- 新增 `GET /embedding/status`，只读返回 provider、模型、就绪状态和是否需要初始化。
- 新增显式初始化命令：`python -m app.index.prepare_embeddings`。
- 新增只检查、不触发下载的命令：`python -m app.index.prepare_embeddings --check`。
- README 与 `.env.example` 已同步初始化步骤和 PDF 上传配置。

##### 工程验证

- 新增限定范围检索、Chroma filter、BM25 scope、中文切分、引用校验、索引回滚和 PDF 限流测试。
- 后端测试由 14 个增加到 27 个，结果为 `27 passed`。
- 前端 `npm run lint` 零警告，`npm run build` 通过。
- Python `compileall` 与 `git diff --check` 通过。
- 新增 `backend/requirements-dev.txt` 和 GitHub Actions CI，持续执行后端测试、前端 lint 与生产构建。

##### 兼容性说明

- 默认 embedding 模型没有更换，已有英文 Chroma 索引可继续使用。
- 已入库中文论文若要应用新的 CJK 分块策略，需要重新导入或重建索引。
- 切换 embedding provider 或模型仍应重建向量索引，不能混用不同模型生成的向量。

#### 停止生成与任务取消（2026-07-17）

本轮增加端到端聊天取消能力。停止操作不仅结束前端加载状态，也会向后端传播取消信号，终止对应的 Agent/LLM 任务。

##### 前端交互

- 每次聊天生成都会创建唯一 `request_id` 和独立 `AbortController`。
- 生成期间发送按钮切换为带方形停止图标的「停止」按钮；也可以按 `Esc` 停止。
- 停止时同时中止 SSE 读取并调用 `DELETE /chat/tasks/{request_id}`。任一取消信号到达后端即可终止任务。
- 后端通过 `started` 事件提前返回 `session_id`。停止后前端重新加载该会话，保留已经发送的用户问题。
- 未完成的 assistant 回答不会写入聊天记录；界面显示「已停止生成」，用户可以继续修改问题或重新发送。

##### 后端任务模型

- `/chat/stream` 不再为每个请求创建 daemon thread，改为注册具名 `asyncio.Task`。
- 活动任务按 `request_id` 保存；重复使用仍在运行的 ID 返回 HTTP 409。
- 客户端断开、显式取消接口和 StreamingResponse 清理都会调用 `task.cancel()`。
- SSE 事件增加 `started` 与 `cancelled`，完整终态为 `done`、`error` 或 `cancelled`。
- 任务结束后从活动注册表移除，并等待取消清理完成，避免后台遗留聊天线程。

##### 可取消执行链

- 意图识别、普通 RAG、方法对比及综述各阶段的模型调用由同步 `invoke` 改为异步 `ainvoke`。
- Semantic Scholar/arXiv 在线检索沿用异步 HTTP，可随外层任务一起取消。
- Chroma/BM25 本地检索通过 `asyncio.to_thread` 避免阻塞事件循环；若取消发生在本地检索中，结果会被丢弃，不会继续进入模型生成或写入 assistant 消息。
- `asyncio.CancelledError` 不会被综述 fallback 或普通错误处理捕获，因此不会在用户停止后意外启动降级生成。

##### 协议与验证

- `ChatRequest` 新增受格式和长度约束的可选 `request_id`。
- 新增 `DELETE /chat/tasks/{request_id}`，重复取消或任务已结束时保持幂等。
- 新增任务注册取消、SSE `started -> cancelled` 事件和异步模型调用取消测试。
- 后端完整测试结果更新为 `32 passed`；前端 lint 与生产构建通过。
