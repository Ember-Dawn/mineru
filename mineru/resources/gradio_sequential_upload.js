// Gradio 6 HTML js_on_load: `upload(file)` uploads exactly one File per call.
// Each await completes before the next request starts. No batched multipart POST.
const root = element;
let active = false;
const status = () => root.querySelector('.mineru-sequential-progress');
const setStatus = (text) => { const node = status(); if (node) node.textContent = text; };
const accept = (file) => /\.(pdf|png|jpg|jpeg|webp|bmp|tif|tiff|doc|docx|ppt|pptx|xls|xlsx|html|htm|mhtml|epub|ofd)$/i.test(file.name);
const enqueue = async (files) => {
    if (active || window.__mineruSequentialUploaderLocked) return;
    const selected = Array.from(files || []).filter(accept);
    if (!selected.length) { setStatus('没有可上传的支持文件'); return; }
    active = true;
    const paths = [];
    const failures = [];
    try {
        for (let i = 0; i < selected.length; i++) {
            const file = selected[i];
            setStatus(`正在上传第 ${i + 1}/${selected.length} 个：${file.name}`);
            try {
                // Official Gradio helper handles mount prefixes/authentication.
                const result = await upload(file);
                if (!result?.path || typeof result.path !== 'string') throw new Error('上传结果无效');
                paths.push(result.path);
            } catch (error) {
                failures.push(`${file.name}: ${error?.message || String(error)}`);
            }
        }
    } finally {
        active = false;
    }
    setStatus(`已上传 ${paths.length}/${selected.length} 个文件`);
    if (paths.length) { props.value = {html: root.innerHTML, paths}; trigger('submit'); }
    if (failures.length) alert('以下文件上传失败：\n' + failures.slice(0, 8).join('\n'));
};
root.addEventListener('change', (event) => {
    const input = event.target.closest?.('.mineru-sequential-input');
    if (!input) return;
    const files = Array.from(input.files || []);
    input.value = '';
    void enqueue(files);
});
root.addEventListener('dragover', (event) => {
    if (!event.target.closest?.('.mineru-sequential-dropzone')) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
});
root.addEventListener('drop', (event) => {
    if (!event.target.closest?.('.mineru-sequential-dropzone')) return;
    event.preventDefault();
    void enqueue(event.dataTransfer?.files);
});
root.addEventListener('click', (event) => {
    const button = event.target.closest?.('.mineru-sequential-remove');
    if (!button || active || window.__mineruSequentialUploaderLocked) return;
    event.preventDefault();
    props.value = {html: root.innerHTML, index: Number(button.dataset.index)};
    trigger('edit');
});
