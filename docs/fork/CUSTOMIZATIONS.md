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

## 维护规则

每次新增或修改定制，更新上述对应章节的文件列表、配置、验证状态及升级风险。删除定制时明确注明该行为已由官方接管或不再需要。历史细节可通过 Git 提交记录查询。

## 5. Gradio EasyImages Markdown export

**Purpose**: optional export of a standalone Markdown file with hosted image URLs, without modifying the parsed Markdown or image assets.

- Files: `mineru/kit/gradio/image_host.py`, `mineru/kit/gradio/app.py`, `docker-compose.yml`, `.env.example`, related tests and WebUI docs.
- Configuration: `EASYIMAGES_API_URL` is the HTTPS site root; `EASYIMAGES_TOKEN` is server-side only, injected into `mineru-webui`.
- Behavior: user-initiated; images referenced by Markdown are uploaded serially with a shared 0.6-second start interval, retry on transient errors, per-run success cache, then standalone MD download.
- Validation: lightweight local checks only; real Cloudflare/EasyImages integration and browser interaction require deployment testing.
- Upgrade risk: low to medium; review Gradio event/state APIs when syncing upstream.

## 6. Docker model-base build and WebUI development mount

**Purpose**: decouple expensive model preparation from ordinary application-source edits; let Gradio updates load after a WebUI restart without rebuilding.

- `Dockerfile.models` contains the original full model-preparation build and produces `mineru:model-base` (one-time / explicit refresh).
- `Dockerfile` inherits `mineru:model-base`, copies application source, and installs the local package with `--no-deps`.
- `docker-compose.dev.yml` bind-mounts `./mineru` into WebUI only; `PYTHONPATH=/opt/mineru-source` ensures Python imports mounted code. The Router remains isolated from development edits.
- Initial migration: after the *previous* full build finishes successfully, use `docker image tag mineru:local mineru:model-base` before rebuilding `mineru:local`. If no compatible old image exists, build the base explicitly using `docker build -f Dockerfile.models -t mineru:model-base .`.
- Model or third-party dependency updates require an explicit base-image rebuild, followed by application image rebuild and the necessary container recreation. Do not mistake a source-only build for a dependency/model update.
- Verification: static Compose/Dockerfile checks only in this patch; actual image build, module import path and Docker restart need host-side validation.
- Upgrade risk: medium; verify package/requirements and model registry compatibility whenever upstream MinerU changes.
