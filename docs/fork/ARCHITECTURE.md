# Fork 关键架构与设计决策

仅记录 Fork 定制的调用链，不重复官方 MinerU 全部架构。

## 部署和调用关系

```text
浏览器
  │ http://服务器:9091
  ▼
mineru-webui (Gradio, :7860)
  │ HTTP http://mineru-router:8002
  ▼
mineru-router (:8002；宿主机 :9094)
  │ 管理本地 worker / 健康检查
  ▼
mineru-kit api-server (Router 容器内的独立子进程)
  ├── OCR / Layout 等非 VLM 模型缓存
  └── VLM 缓存 (vLLM Async Engine / EngineCore)
       ├── 解析任务触发按需加载
       ├── 任务结束更新最后活动时间
       ├── 无活动任务且超过 idle_minutes
       ├── shutdown_cached_models()
       └── 后续新任务应按需重新加载（需实测）
```

WebUI 并不是额外的模型推理服务；`--api-url` 将请求发送给 Router。Router 的本地 Worker 由 Router 进程托管，独立 `mineru-api` 服务在当前 Compose 中并未启动。

## 空闲卸载的实现边界

- 配置流：`docker-compose.yml` → `kit/router/cli.py` → `RouterSettings` → `ManagedLocalWorker.command()` → `kit/main.py` → `kit/commands/api_server.py` → `parser/api_server.py` Click → `create_app()` → `JobStore`。
- `JobStore` 根据任务活动时间和 `_tasks` 判断是否满足卸载条件；后台循环在 FastAPI lifespan 内运行。
- `_model_idle_gate` 用于避免卸载与新任务接纳交错；关闭过程通过 `run_sync(shutdown_cached_models)` 执行。
- `shutdown_cached_models()` 关闭 VLM 缓存模型；不以停止整个 Worker 作为释放策略。
- 空闲监控以「任务真正结束后的空闲」为依据，而不是以容器启动时间为依据。未使用过模型不应为卸载而强行加载它。
- 卸载异常时停止本轮生命周期中的后续自动卸载尝试。重载后显存回收要通过实机验证，不能只依赖单元测试。

## 为什么没有采取其他方案？

- **杀掉 Worker**：会破坏服务连续性并产生重建开销；用户明确希望容器和 Worker 保持运行。
- **vLLM Sleep Mode**：属于不同的显存生命周期机制，当前改造没有依赖它；未来若上游支持，可与直接 shutdown 方案比较。
- **WebUI 独立 GPU 推理**：当前没有必要，会造成重复模型占用。
- **源码目录直接保存模型**：当前选用 BuildKit 的跨构建缓存及最终镜像打包模型；用户决定暂时不迁移到项目目录。

## 修改时首要检查

- `kit/main.py` 的实际命令注册和 `kit/commands/api_server.py` 是否一致。
- `parser/api_server.py` 的 JobStore 活动状态是否覆盖所有任务完成/取消路径。
- `model/vlm/runtime.py` 中卸载函数是否仍支持释放后再次加载。
- Router 真实健康检查和 WebUI API 连接是否正常。
