// 移除聊天正文里指向【工作区相对路径】的 markdown 图片语法(如 ![柴犬](media/picture/x.png))。
//
// 为什么:工作区图片必须走带登录 token 的 /api/files/raw 才取得到;模型若在正文用 markdown
// 写裸相对路径,react-markdown 会渲染成 <img src="media/picture/x.png">,浏览器相对当前页解析
// → 404 → 破损图标。而这些图本就由 generate_image 的工具卡片(或文件预览)展示过,正文重复
// 既多余又破损。故在【聊天正文】渲染前剥掉它们(不动 Markdown 组件本身——它还要渲染工作区
// 文件预览,且有"绝不放开 img/urlTransform"的 XSS 红线)。
//
// 保留外部 http(s) 图片(那些能正常加载,不该误伤)。alt/url 限定不跨行,避免吞掉多行内容。
const WORKSPACE_IMG_MD = /!\[[^\]\n]*\]\(\s*(?!https?:\/\/)[^)\n]*\)/g

export function stripWorkspaceImageMarkdown(text: string): string {
  if (!text.includes("![")) return text // 绝大多数正文无图,快速短路
  return text
    .replace(WORKSPACE_IMG_MD, "")
    .replace(/[ \t]+\n/g, "\n") // 清掉删除后残留的行尾空白
    .replace(/\n{3,}/g, "\n\n") // 折叠多余空行
    .trim()
}
