# Fork 定制功能清单（以当前源码为准）

本文记录**现状**，不是所有历史提交的流水账。对每项定制，说明目的、机制、具体文件、配置、验证和升级风险。

## 1. API Worker 中 VLM 空闲自动卸载

**目的**：长时间不解析时回收大模型显存，但保持 Router、Worker 与 WebUI 存活，避免反复重启整个服务。

**主要修改文件**：

- `mineru/parser/api_server.py`：在 `JobStore` 跟踪任务活动和完成时间；使用异步锁协调任务接纳与卸载；空闲循环调用 `shutdown_cached_models()`。
- `mineru/kit/router/cli.py`：Router `--model-idle-minutes` CLI 选项。
- `mineru/kit/router/workers.py`：`RouterSettings` 保留配置，启动本地 API Worker 时转发参数。
- `mineru/kit/commands/api_server.py`：Typer `api-server` 入口接收并转发至底层 Click 命令。
- `tests/unittest/test_model_idle_unload.py`：空闲卸载和 CLI 参数路径回归测试。
- `docker-compose.yml`：在 Router 启动参数中配置空闲阈值。

**复用而非本次新建的现有机制**：

- `mineru/model/vlm/runtime.py`：`shutdown_cached_models()` / VLM 运行时关闭入口。它是卸载执行端，不应误记为本轮必然修改过的文件。

**配置**：`--model-idle-minutes N`，单位分钟；`0` 表示禁用。Docker Compose 仓库配置曾设 `30`，用户测试时改为 `2`；**当前部署生效值以实际 Compose 文件为准**。

**行为边界**：仅在曾有任务活动、无运行任务且超过阈值时卸载缓存 VLM；其他 OCR/Layout 等模型的生命周期不由此机制主动关闭。关闭异常会记录日志并禁止继续尝试，以免循环故障。后续任务应重新按需加载 VLM，需实机验证完整链路。

**验证状态**：

- 已观察：Router/WebUI 不中断，`VLLM::EngineCore` 退出；GPU 总占用从 **7,283 MiB** 降至 **728 MiB**（下降 6,555 MiB），vLLM 日志出现 `Shutdown initiated` / `Shutdown complete`。
- 未确认：卸载后**再次解析并自动重新加载**的完整实机回归测试。
- 仅有针对性代码检查和测试用例，不能将其等同于全量测试。

**升级风险：高**。官方若修改 JobStore、模型运行时缓存、CLI 入口或 Worker 调度，必须重审任务同步及释放安全性；若官方提供原生空闲卸载，先比较再决定是否移除定制。

## 2. Router → API Worker 参数贯通

**目的**：避免 Router 已接受参数，但被托管 API Worker 报 `No such option '--model-idle-minutes'`。

**文件**：

- `mineru/kit/main.py`：实际根命令注册路径（供阅读，非本轮新增）。
- `mineru/kit/commands/api_server.py`：中间 Typer 命令入口的参数注册及向 Click 转发。
- `mineru/parser/api_server.py`：底层 Click 接收参数并传入 App/JobStore。
- `mineru/kit/router/workers.py`：构造 Worker CLI 参数。
- `tests/unittest/test_model_idle_unload.py`：Typer 帮助、有效值、非法值和转发回归。

**已验证**：修复后 Router 健康检查 HTTP 200、WebUI 正常启动。升级时需要走真实 `mineru-kit api-server --help` 和 Worker 启动链路，不能只测内部函数。

## 3. 本地 Docker 双服务部署

**目的**：部署自定义源码，统一推理入口，WebUI 不重复占用 GPU。

**文件**：仓库根 `Dockerfile`、`docker-compose.yml`；`.dockerignore` 提供构建上下文排除规则。

**当前形态**：

- `mineru-router`：宿主机 `9094` → 容器 `8002`；托管 GPU 0 上的本地 API Worker；部署保留 NVIDIA GPU reservation。
- `mineru-webui`：宿主机 `9091` → 容器 `7860`；`--api-url http://mineru-router:8002`；等 Router healthy 后启动；WebUI 自身不申请 GPU。
- 官方可选独立 API 和 OpenAI Server 在 Compose 中以注释形式保留，不参加当前启动。
- 镜像名称 `mineru:local`；使用仓库根 `Dockerfile` 从本地源码安装。

**已验证**：Router healthy、WebUI 已启动，API `/v1/health` 和 `/v1/tiers` 返回 200；GPU 上实际加载并卸载过 VLM。

**升级风险：中**。关注服务 CLI、健康检查路由、模型目录和 GPU 镜像兼容性；不要无依据恢复多余推理服务。

## 4. BuildKit 模型缓存

**目的**：修改源码导致 Docker 构建层失效时，避免完整重复下载模型。

**文件**：`Dockerfile`。

**缓存标识**：

- `mineru-standard-models` → 构建容器 `/root/.mineru/models`。
- `mineru-hf-xet` → 构建容器 `/root/.cache/huggingface`。
- 均使用 `RUN --mount=type=cache,...,sharing=locked`。
- 下载完成将模型复制至镜像临时目录，后续恢复到 `/root/.mineru/models`，确保运行时不依赖 BuildKit 缓存。

**限制**：BuildKit 缓存由 Docker 管理，不在源码目录内；不是永久备份；首次引入缓存时旧镜像内容不会自动迁入；缓存清理后仍可能重新下载。源码仍在 pip 安装之前复制，依赖安装层尚未独立优化。

**升级风险：中**。检查官方模型路径、模型下载 CLI、镜像基础层及缓存迁移。

## 5. Gradio EasyImages Markdown export

**Purpose**: optional export of a standalone Markdown file with hosted image URLs, without modifying the parsed Markdown or image assets.

- Files: `mineru/kit/gradio/image_host.py`, `mineru/kit/gradio/app.py`, `docker-compose.yml`, `.env.example`, related tests and WebUI docs.
- Configuration: `EASYIMAGES_API_URL` is the HTTPS site root; `EASYIMAGES_TOKEN` is server-side only, injected into `mineru-webui`.
- Behavior: user-initiated; images referenced by Markdown are uploaded serially with a shared 0.6-second start interval, retry on transient errors, per-run success cache, then standalone MD download.
- Validation: lightweight local checks only; real Cloudflare/EasyImages integration and browser interaction require deployment testing.
- Upgrade risk: low to medium; review Gradio event/state APIs when syncing upstream.

## 6. 单 Dockerfile 与默认 WebUI 源码挂载

**目的**：恢复完整单镜像构建，简化个人开发环境；Gradio 源码修改后仅重启 WebUI，不重复构建 GPU 镜像。

- `Dockerfile`：使用 vLLM 基础镜像，安装 MinerU 及 Torch 依赖，执行 Standard/Torch/vLLM 模型准备，保留 `mineru-standard-models` 与 `mineru-hf-xet` BuildKit 缓存；复制模型到最终镜像的 `/root/.mineru/models`。
- `docker-compose.yml`：只给 `mineru-webui` 挂载 `./mineru:/opt/mineru-source/mineru:ro`，并设置 `PYTHONPATH=/opt/mineru-source`；Router/Worker 始终使用镜像内源码。
- `mineru/kit/commands/models.py`：模型下载 CLI 传入 `reuse_ready=True`，已满足本地就绪条件的模型仓库可直接复用。
- 删除此前引入的 `Dockerfile.models` 与 `docker-compose.dev.yml`，不再需要 `mineru:model-base`。

**使用**：切换方案时重新构建完整 `mineru:local` 并重新创建容器；之后仅改 Gradio/图床 Python 源码，运行 `docker compose restart mineru-webui`。依赖、模型或 Router/Worker 变更仍需重建镜像及对应容器。

**边界**：`COPY .` 仍在模型下载之前，源码变化会使其构建层重新执行；BuildKit 缓存及 `reuse_ready=True` 只是减轻重复下载。`reuse_ready=True` 使用本地完成标记/必要路径验证，不等于完整哈希校验，亦不会自动检查远端权重更新；主动升级模型时必须制定刷新方案。

**验证**：已执行轻量 Python 语法、Compose YAML 和 ZIP 完整性检查；实际 Docker 构建、挂载导入路径及 GPU 推理需在服务器验证。升级风险中等。

## 维护规则

每次修改定制，更新涉及文件、配置、实测结论和升级风险；不要把未执行的实机测试标成已通过。

## 7. Gradio 串行批量解析与运行期历史

**目的**：一个上传入口兼容单个或多个文档；多个 PDF 按原顺序依次解析；解析完成后可下载统一 ZIP 或手动生成批量图床版 Markdown，刷新页面可恢复完成的任务结果。

**实现文件**：`mineru/kit/gradio/batch.py`（批次、进程内历史、ZIP）、`app.py`（多文件输入、协调、恢复、操作锁）、`gradio_page_range.js`（批量时隐藏单文件页码）、`gradio_conversion.js`（恢复回执身份）、`gradio_app.css`（紧凑队列与下载区域）、`i18n.py`、`tests/unittest/test_kit_gradio_batch.py`。

- 保留原来的单文件 Gradio 预览组件作为隐藏内部适配器：外层 File 多选后，第一份文件提供给旧预览链路，避免让原 PDF/Office 浏览器脚本直接接收文件数组。
- 多文件解析仅接受 PDF，一次批次使用一个顶层会话任务，内部逐个执行，共享原有 `SessionConversions.slot`，每份结果仍保存于独立 `RunArtifacts` 目录。
- 单文件继续支持原有文件类型、页码范围和右侧下载菜单；批量不提供逐份页码范围，按每份文档的全页与原有最大页数限制执行。
- ZIP 单文件复用原有 Markdown ZIP；多文件只包含成功解析文档的 Markdown 和图片，失败项列入 `处理报告.txt`。
- EasyImages 只在批次解析结束后手动执行；同批次依次调用既有 `image_host.generate()` 并沿用 0.6 秒共享限速和任务级缓存；单文件下载 MD，多文件生成图床版 MD ZIP。
- 历史采用 WebUI **进程内**索引，刷新后可选择恢复已结束任务的预览、当前下载目标及图床状态，不重跑解析；不增加数据库、数据卷、容器重建后的保留保证。清除历史只删除索引，不删除磁盘产物。
- 解析和图床处理中禁用清除、文件上传、转换及历史恢复；后端另外拒绝忙碌期间的恢复/清除历史。刷新正在执行的任务不保证继续。

**兼容性**：单文件公开转换 API/原有下载机制保留；现有七种右侧下载仍针对选中任务的最后一份成功结果。重型 GPU/浏览器实测需要在本地完成。


## 批量左栏 UI 整理
- 上传之前可多次选择文件并服务端累积清单（同名、大小、SHA-256 去重）；清除重置清单。
- 批量解析隐藏单文件页码控件，所有文件采用完整范围，遵循服务端页数上限。
- 批次统计、进度条和失败清单位于最新状态卡片内部，成功文件不逐条列出。
- 下载 ZIP 改为独立按钮，可用为 `#ea580c`，禁用为 `#52525b`。
- 历史记录简化为下拉框及恢复、清除按钮，不需要手动刷新。

## 上传与状态区交互修正

- 多次选择 PDF 采用 Gradio `File.upload` 独立事件追加到服务端列表；`File.delete` 删除单项，`File.clear` 清空。完整队列回写 File 组件，避免显示和任务清单不一致。
- 保留同名/大小/SHA-256 去重，解析或图床处理期间禁止更改。
- 单文件的页码脚本不再显示「不限页数」提示，不改变实际页码限制。
- 下载 ZIP 移至最新状态面板底部并缩小，图床卡片移除重复标题。
- Gradio 浏览器原生上传、删除事件仍需要实际部署验收。

## 上传与状态区交互修正

- File.upload 追加到服务端队列，File.delete 删除单项，File.clear 清空；回写完整队列。
- 单文件页码标尺移除「不限页数」提示，不改变限制逻辑。
- ZIP 按钮内移至最新状态底部、缩小；图床标题删除。
- 真实浏览器行为仍需 Gradio 运行时验证。
