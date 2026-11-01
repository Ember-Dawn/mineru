# Gradio 图床卡片样式约定

EasyImages 图床导出在 Gradio 左侧解析状态卡片下方，以独立紧凑卡片展示。

- `mineru/kit/gradio/app.py`：使用 `gr.Column`、`gr.HTML` 标题、原生按钮和状态组件；不修改上传处理和回调逻辑。
- `mineru/resources/gradio_app.css`：复用状态卡片的边框、背景、圆角、内边距与深浅主题变量。按钮可用时采用已有橙色主题，禁用时保留 Gradio 原生禁用表现。
- `mineru/kit/gradio/i18n.py`：标题、初始按钮及等待提示经现有中英文字典显示，不再同时写两种语言。
- 后续如需调整动态进度/错误文案的国际化，应单独验证 Gradio 更新事件；不要把纯样式调整与上传流程重构混合。
- 轻量验证：已检查源码 Git blob SHA、Python AST 与 ZIP CRC；暗色/亮色浏览器外观及真实上传仍需在部署后人工检查。

日常修改上述挂载源码或样式后，重启 `mineru-webui` 并刷新浏览器即可；不需重建镜像。

## 图床按钮回归修复

- 当前 WebUI 转换流程保存解析结果于服务端 `ConversionRun.artifacts`，并未填充供图床回调读取的 `artifact_state`。图床回调改用 `active_run_id` 及服务端当前 run 校验，解决转换成功后错误提示 `No parsed document is available`。
- 恢复被上轮 CSS 插入误伤的 `.block.mineru-status-panel .status-steps-panel` 规则；限定图床启用按钮橙色背景、白色文字。
- 已完成 Python AST、Git SHA 及 ZIP 完整性轻量检查；真实图床上传和 Gradio 浏览器联动仍需服务器验证。


## 图床下载去重与按钮视觉统一

- 图床按钮采用与转换按钮一致的 `--mineru-accent` 橙色、白色文字；字号为 16px、加粗，压缩内部 padding。
- 针对 Gradio 隐藏 File 组件可能重复派发的 `change` 通知，浏览器对同一 URL 两秒内的重复触发做去重；较晚的再次手动点击仍允许下载。
- 此策略避免短时间重复下载，但不是跨所有事件的永久幂等保证；真实浏览器行为仍需实机验证。
- 未更改后端图床上传、任务识别、模型或 Docker 配置。
