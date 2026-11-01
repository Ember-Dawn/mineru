# Fork Docker 部署和排障

## 当前默认部署

在仓库根目录运行 Docker Compose，镜像由本地 `Dockerfile` 构建，通常为 `mineru:local`。

| 服务 | 宿主端口 | 容器端口 | 用途 |
|---|---:|---:|---|
| `mineru-webui` | 9091 | 7860 | 浏览器解析 UI |
| `mineru-router` | 9094 | 8002 | V1 API 与本地 Worker |

WebUI 使用内部地址 `http://mineru-router:8002` 与 Router 通信，Router 使用 GPU 0，WebUI 默认不占用 GPU。

- 本机 WebUI：`http://localhost:9091`；局域网 / Tailscale 用服务器相应 IP。
- API 文档：`http://服务器IP:9094/docs`（实际可用路由应以服务为准）。
- Docker `ports` 发布到网络接口并不保证符合 UFW 预期；不要假定普通 UFW 入站规则能完全限制已发布的 Docker 端口。
- 当前部署无模型目录 bind mount：模型保留于 `mineru:model-base` / 派生镜像，初次模型构建仍使用 BuildKit 缓存。
- 用户以 git-bridge 同步代码；日常说明无需提供 Git 同步操作。

## 模型基础镜像与日常构建

模型与第三方依赖由 `Dockerfile.models` 准备为 `mineru:model-base`；普通 `Dockerfile` 仅在这一基础上安装当前仓库源码。两类镜像需要明确区分：源码变更无需模型下载，依赖或模型版本变更则必须显式刷新基础镜像。

**首次迁移（已有旧完整镜像时，优先采用）**：让当前旧 Dockerfile 构建彻底成功后，在尚未应用本次新 Dockerfile 前执行 `docker image tag mineru:local mineru:model-base`。该操作不复制或下载模型数据。之后应用补丁，并执行 `docker compose build mineru-webui` 或 `docker compose up -d --build ...`。不要在旧构建未成功时提前标记模型基础镜像。

**没有可用旧镜像，或主动升级模型/依赖**：

```bash
docker build -f Dockerfile.models -t mineru:model-base .
docker compose build mineru-webui mineru-router
docker compose up -d
```

刷新基础镜像后不能仅使用 `docker compose restart`：旧容器仍绑定旧镜像，需要重新创建相应容器。重建 Router 会影响正在运行的解析任务。

**日常修改 Gradio（开发模式）**：

```bash
# 首次启用源码挂载（会重建 WebUI 容器，但不重建模型）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --no-deps --force-recreate mineru-webui

# 后续修改 Gradio/Python 文件，仅需重启 WebUI
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart mineru-webui
```

开发 override 只挂载 `./mineru` 到 WebUI，Router 不受影响。`PYTHONPATH` 使 Python 首先使用被挂载的源码；如需确认：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec mineru-webui \
  python3 -c 'import mineru; print(mineru.__file__)'
```

路径应以 `/opt/mineru-source/mineru/` 开头。若修改 `pyproject.toml`、第三方依赖、系统依赖、模型注册表或基础镜像，需要相应重新构建，而非仅重启。纯 `docker compose restart` 不会重新应用变化的 `.env`/Compose 配置；应使用 `up -d` 重建相关容器。只修改 Gradio/图片上传模块的 `.py`、所挂载的 CSS/JS 资源时，可使用开发模式重启；浏览器端可能还需强制刷新。

**普通部署（不用开发 override）**：

```bash
docker compose up -d --build
```

不要随意使用 `--no-cache`、`docker builder prune`、`docker system prune -a` 或 `down -v`；这些可能清理模型缓存或镜像。`mineru:model-base` 应作为重要的本地构建基础保留。

## 验证 CLI 与模型卸载配置

```bash
docker compose config | grep -A 3 -B 3 model-idle-minutes
docker compose exec mineru-router mineru-kit api-server --help | grep -i -C 2 idle
docker compose ps
nvidia-smi
```

过去遇到过 Router healthy 失败：原因是 Router 向 Worker 传递 `--model-idle-minutes`，但 `kit/commands/api_server.py` 的 Typer 入口没有注册；后续已补齐。若复现应先检查实际镜像及 CLI，不要盲目改 GPU / 健康检查。

## 空闲卸载实测步骤

1. 用 WebUI 执行一次真实 Hybrid / Standard 文档解析；不以刚启动无模型状态为测试对象。
2. 解析完成后记录 `nvidia-smi`；停止提交新任务。
3. 等待配置阈值加上轮询余量，持续观察 GPU 进程与显存。
4. 查看 vLLM `Shutdown initiated` / `Shutdown complete`，检查 `VLLM::EngineCore` 进程是否退出。
5. 确认 Router healthy 且 WebUI 仍运行；再次提交任务验证自动加载和结果输出。

历史一次测试中显存 **7,283 MiB → 728 MiB**、vLLM 退出成功；但“卸载后自动重新加载并完成解析”的最终闭环没有保存完整确认记录。

## 模型缓存

`Dockerfile.models` 中 `mineru-standard-models` 与 `mineru-hf-xet` 是 BuildKit 缓存 ID，而 `target` 是构建容器路径，不是宿主机的 `/root/...`。最终镜像模型仍位于 `/root/.mineru/models`。日常 `Dockerfile` 不再执行该下载步骤。缓存可能被清理，不代替模型备份；首次采用新缓存策略可能重新下载。

## WebUI 下载异常（待验证）

历史现象：预览已显示解析内容，点击 Markdown / JSON 下载弹 `No parsed document is available`。对应 `kit/gradio/artifacts.py` 中 State 非字典异常。调查过会话状态覆盖，但**不能确定根因**；后续用户曾重新构建尝试，未留存修复结论。

排查建议：

```bash
docker compose logs --tail=120 mineru-webui
docker exec mineru-webui sh -c 'readlink -f /proc/1/cwd; tr "\000" " " < /proc/1/cmdline; echo'
docker exec mineru-webui sh -c 'find /opt/mineru-source /app /tmp /root -type f \( -name markdown.md -o -name structured_content.json \) 2>/dev/null | tail -30'
```

若需要复现，请先用 1~3 页小 PDF，保存浏览器 Console、WebUI 日志、当前会话和生成文件路径；不要在确认文件保存位置前删除容器。

## EasyImages2.0 (optional)

Copy `.env.example` to `.env` and fill `EASYIMAGES_API_URL` (HTTPS site root such as `https://easyimages.380782744.xyz`) and `EASYIMAGES_TOKEN`. Compose passes these only to `mineru-webui`. The WebUI app appends `/api/index.php` automatically. Never commit `.env` or print the token.

After a successful conversion use the image-hosting card below the conversion status; the original Markdown ZIP remains unchanged. Uploads are serial, spaced at least 0.6 seconds between start times. Verify real Cloudflare behavior and link accessibility in the deployed environment.
