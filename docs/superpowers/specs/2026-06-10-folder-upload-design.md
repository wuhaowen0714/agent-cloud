# 文件夹上传设计

**日期:** 2026-06-10
**状态:** 设计已批准

## 目标

文件抽屉支持上传整个文件夹(保留目录结构),与现有单/多文件上传并存。

## 设计

- **前端**:`FileToolbar` 新增「↑ 上传文件夹」按钮 + 隐藏 `<input type="file" webkitdirectory multiple>`(现代浏览器全支持);`api.uploadFiles` 把每个文件以 `fd.append("files", f, f.webkitRelativePath || f.name)` 追加——multipart filename 携带相对路径(如 `proj/sub/a.txt`),普通文件上传零影响。
- **后端**(`POST /files/upload`):原本把 filename 削成 basename(消毒)。改为**保留相对路径的消毒** `_sanitize_rel_upload_path`:`\` → `/` 归一(Windows 风格)、拒 `\0`、按 `/` 分段丢弃空段与 `.`、出现 `..` 或结果为空 → `PathEscape`(400,提前拦);随后 `store.write` 自建父链,`store._resolve` 仍是最终围栏——**双层防护,越狱面不扩大**。覆盖语义沿用现状(同名原子替换)。
- **README**:文件管理特性行注明支持文件夹上传。

## 限制(YAGNI)

- 浏览器目录选择 API 不上报**空目录**(不会被创建)。
- 拖拽整文件夹进抽屉(`webkitGetAsEntry` 遍历)v1 不做;无上传进度条。

## 测试

- 后端:多文件带子路径 → 嵌套落盘且返回 path 正确;`../evil.txt` → 400;`win\style.txt` → 归一为 `win/style.txt`;普通 basename 上传不回归;上传到子目录(`?path=d`)与相对路径拼接正确。
- 前端:工具栏存在「上传文件夹」按钮与带 `webkitdirectory` 属性的 input;选择文件触发上传调用。
