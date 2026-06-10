# 文件预览渲染(md / html)设计

**日期:** 2026-06-10
**状态:** 设计已批准

## 目标

文件抽屉预览 `.md/.markdown` 与 `.html/.htm` 时**渲染展示**而非裸源码;头部提供「渲染 / 源码」切换(默认渲染)。

## 设计

- **`previewKind`**(`files.ts`)扩两类:`markdown`、`html`(优先级:图片 > 超过 1MB → download > md > html > text;两类同样受 1MB 上限约束)。
- **Markdown**:fetch 文本后复用聊天区现成 [`Markdown`](../../frontend/src/components/Markdown.tsx) 组件(react-markdown + GFM,**默认转义内嵌 HTML,无 XSS 面**)。
- **HTML(安全关键)**:工作区文件是 agent/用户生成的任意内容,绝不同源渲染。用**沙箱 iframe**:`<iframe sandbox="allow-scripts" src={blobUrl}>`,**不给 `allow-same-origin`** → 文档在 opaque origin 中运行:摸不到父页面与 token、请求不带凭据(SameSite=Lax cookie 对跨站子资源不下发)。允许脚本让 demo 可跑(Claude artifacts 同款取舍)。
- **「渲染 / 源码」切换**:`FilePreview` 头部按钮,仅 markdown/html 显示;源码视图即现有 `<pre>` 文本路径。markdown/html 均预取文本(源码切换零等待);html 另持 blob URL 供 iframe。
- 失败路径沿用现状(err → 「无法预览,请下载查看。」;下载 catch 已有)。

## 非目标(YAGNI)

HTML 内相对路径资源(`./img.png`)在 blob/opaque origin 下不可加载,v1 不解;不做 csv/pdf/ipynb 等其它格式;不做渲染偏好持久化。

## 测试

- `previewKind`:`.md → markdown`、`.html → html`、超 1MB 的 md/html → download、`.txt` 仍 text。
- `FilePreview`:md 渲染出标题(react-markdown);html 走 iframe 且 `sandbox="allow-scripts"`(**不含** allow-same-origin)、`src` 为 blob URL;点「源码」显示原文 `<pre>`;失败路径既有测试不回归。
