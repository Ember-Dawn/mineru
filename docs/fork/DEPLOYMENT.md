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
- 当前部署没有模型目录 bind mount：模型保留于 `mineru:local` 镜像，构建时使用 BuildKit 缓存。
- 用户以 git-bridge 同步代码；日常说明无需提供 Git 同步操作。

## 单 Dockerfile 构建与默认 WebUI 开发模式

仅使用仓库根目录的 `Dockerfile` 构建 `mineru:local`，包括系统依赖、Python 环境和模型。Router 与 WebUI 继续共用镜像，WebUI 默认以只读 bind mount 加载宿主机 `./mineru` 源码。

切换回单 Dockerfile 后，首次重建：

```bash
cd ~/app/mineru
docker compose up -d --build
docker compose ps
```

以后仅修改 Gradio 或 EasyImages Python 源码：

```bash
docker compose restart mineru-webui
docker compose exec mineru-webui python3 -c 'import mineru; print(mineru.__file__)'
```

挂载源码应从 `/opt/mineru-source/mineru/` 加载，可额外运行 `docker inspect mineru-webui --format '{{json .Mounts}}'` 确认只读挂载已生效。重启会中断进行中的 WebUI 请求及上传，不是无中断自动热重载。

修改 `.env` 或 Compose 环境变量，请使用 `docker compose up -d --no-deps mineru-webui` 重新创建容器；仅 `restart` 不会应用新的环境变量。变更依赖、Dockerfile、模型或 Router/Worker 源码仍需重建镜像和相应容器，Router 更新会中断解析任务。

不要随意使用 `--no-cache`、`docker builder prune`、`docker system prune -a` 或 `down -v`，以免清理缓存、镜像或其他数据。

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

单 `Dockerfile` 保留 `mineru-standard-models`（构建时 `/root/.mineru/models`）和 `mineru-hf-xet`（构建时 `/root/.cache/huggingface`）两项 BuildKit 缓存。最终模型复制到镜像内 `/root/.mineru/models`，运行时不依赖 BuildKit 缓存。

模型下载 CLI 现传入 `reuse_ready=True`。已满足 `.mineru_complete` 或必要路径条件的仓库会跳过远端访问；这不代表逐字节完整校验，也不会自动发现模型远端更新。更新模型版本时必须安排受控的缓存刷新与验证，不能只依赖 `docker compose up -d --build`。构建仍可能因为整份源码 `COPY` 改变而重新执行模型准备步骤，但尽量复用现有文件。

不启动 GPU 推理的基本检查：

```bash
docker compose exec mineru-router mineru-kit models verify --tier standard --small-backend torch --vlm-engine vllm
```

BuildKit 缓存不是备份，不在宿主机项目源码目录下。

## EasyImages2.0 (optional)

Copy `.env.example` to `.env` and fill `EASYIMAGES_API_URL` (HTTPS site root such as `https://easyimages.380782744.xyz`) and `EASYIMAGES_TOKEN`. Compose passes these only to `mineru-webui`. The WebUI app appends `/api/index.php` automatically. Never commit `.env` or print the token.

After a successful conversion use the image-hosting card below the conversion status; the original Markdown ZIP remains unchanged. Uploads are serial, spaced at least 0.6 seconds between start times. Verify real Cloudflare behavior and link accessibility in the deployed environment.

## WebUI 批量解析与运行期历史验证

不需要新增 Docker 服务、数据库或目录挂载。应用补丁后仅修改挂载的 WebUI Python/JS/CSS 资源，执行 `docker compose restart mineru-webui` 并强制刷新页面。

用两份小 PDF 检查：多文件选择后按钮显示「批量转换」，按顺序完成并出现一份批量 ZIP；任务结束才可点击图床处理，生成图床版 MD ZIP；解析及图床过程中「清除」与上传不可操作。再刷新页面，通过「历史记录」恢复已完成结果，重新下载，无需再次解析。单 PDF 检查页码选择、旧格式菜单及独立图床 MD。

运行期历史仅在当前 WebUI Python 进程存活期间提供；`docker compose restart`、`up --force-recreate` 或镜像重建后索引重置。磁盘上的原产物不会被「清除历史」删除，但不保证跨容器保留。
