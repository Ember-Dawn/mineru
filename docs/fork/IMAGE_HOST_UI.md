# Gradio 图床卡片样式约定

EasyImages 图床导出在 Gradio 左侧解析状态卡片下方，以独立紧凑卡片展示。

- `mineru/kit/gradio/app.py`：使用 `gr.Column`、`gr.HTML` 标题、原生按钮和状态组件；不修改上传处理和回调逻辑。
- `mineru/resources/gradio_app.css`：复用状态卡片的边框、背景、圆角、内边距与深浅主题变量。按钮可用时采用已有橙色主题，禁用时保留 Gradio 原生禁用表现。
- `mineru/kit/gradio/i18n.py`：标题、初始按钮及等待提示经现有中英文字典显示，不再同时写两种语言。
- 后续如需调整动态进度/错误文案的国际化，应单独验证 Gradio 更新事件；不要把纯样式调整与上传流程重构混合。
- 轻量验证：已检查源码 Git blob SHA、Python AST 与 ZIP CRC；暗色/亮色浏览器外观及真实上传仍需在部署后人工检查。

日常修改上述挂载源码或样式后，重启 `mineru-webui` 并刷新浏览器即可；不需重建镜像。
