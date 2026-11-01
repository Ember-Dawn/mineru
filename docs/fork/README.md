# Ember-Dawn/mineru：Fork 维护入口

> 本目录只记录与 **本 Fork 定制**有关的事实。官方产品能力与编码规范分别以仓库 `README.md` 和根目录 `AGENTS.md`（实际链接到 `CLAUDE.md`）为准。

## 快速认识

- 仓库：`Ember-Dawn/mineru`；官方上游：`opendatalab/MinerU`。
- 历史改造基线：创建 Fork 时对齐过 `mineru-4.0.12-released`；**这不是持续准确的当前上游基线**。升级前必须重新检查 Git 历史和当前 Release。
- 部署：单个 `Dockerfile` 构建完整 `mineru:local` 镜像；WebUI 默认挂载本地源码，修改 Gradio 后重启即可。Router 管理本地 API Worker，WebUI 调用 Router。
- 自定义功能：VLM 空闲卸载、API CLI 参数透传、本地双容器部署、BuildKit 模型缓存、WebUI 默认源码挂载、Gradio EasyImages 图床版 Markdown 导出。
- 同步方式：用户通过 **git-bridge** 管理仓库与服务器同步；无需在日常答复中重复 Git 同步命令。

## 阅读顺序

1. `CUSTOMIZATIONS.md` — 现有定制、文件地图、验证状态。
2. `ARCHITECTURE.md` — 关键调用链及设计约束。
3. `DEPLOYMENT.md` — Docker 配置、排障和运行验证。
4. `UPGRADING.md` — 官方版本更新时的比较、整合与回归流程。

## AI 接手时的约束

1. 先核对 `master` 当前完整源码与 Git blob SHA；文档可能落后于代码。
2. 按任务涉及模块阅读相关源码，不能仅凭本目录改代码。
3. 官方实现和本 Fork 改造要分清；官方升级不等于保留历史定制的每一行代码。
4. 不随意更换 Router / Worker 架构、GPU 设置、模型下载来源或修改未涉及功能。
5. 变更代码时同时更新定制文件列表、验证结论和升级注意事项。
6. 记录事实、实测结果与推测的区别；未实测不要标为已通过。
7. 源码交付优先采用完整文件的增量 ZIP（`payload/`；仅在删除/移动文件时附 `__delete__.txt`）。

## 当前待办/已知风险

- VLM 空闲释放显存已实测；同一 Worker 内卸载后的首次重新解析仍需独立验证。
- Docker BuildKit 缓存不是备份或永久存储，首次切换缓存策略可能重新下载模型。

本目录不保存机器私密信息、Token、SSH 密钥等。
