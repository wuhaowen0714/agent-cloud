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

// Composer 发送带附件的消息时,会在用户文本末尾追加一段【给 agent 看的提示 + 工作区路径】
// (见 Composer.send)。渲染用户气泡时把它摘出来:正文只留用户真正打的字,附件改用缩略图/
// 文件 chip 展示——而不是把内部提示和裸 upload/ 路径直接显示给用户(那既丑又暴露路径)。
// 兼容当前 "Uploaded file(s)" 与早期 "Attached image(s)" 两种 marker。
//
// ⚠️ marker 是【不可信的用户文本】:用户正文里可能恰好出现这串(贴报错、问这个功能本身),
// 不能无脑当分隔符,否则会把 marker 之后的真实正文误吞成"附件"(对抗审查 H1)。故只有当
// marker 之后【每一行都形如工作区路径】(upload//media/ 前缀,Composer 上传落 upload/、
// 生图落 media/)时才剥离;混入其它文本则整体不解析、原样保留正文。
const MARKER_RE = /\[(?:Uploaded file|Attached image)\(s\) in the workspace[^\]\n]*\]\n/
const MARKER_LINE = /^\[(?:Uploaded file|Attached image)\(s\) in the workspace[^\]]*\]$/
const WORKSPACE_PATH = /^(?:upload|media)\//
// /skills 选中的技能,Composer 发送时每个技能追加【独占一行】的 [请使用技能:X];渲染时摘成 chip。
// ⚠️ 整行锚定(^…$):marker 必须独占整行才剥离——用户在正文句中内联打 [请使用技能:x] 不会被
// 误吞(对抗审查 High,与附件 marker 的 H1 防护同源)。每技能一行 → 技能名可含 、, 等任意字符。
const SKILL_LINE = /^\[请使用技能:\s*([^\]]+)\]$/

export function parseUserMessage(text: string): {
  body: string
  attachments: string[]
  skills: string[]
} {
  const normalized = text.replace(/\r\n/g, "\n") // CRLF 归一,否则 marker/路径不匹配会原样暴露
  // 1. 逐行摘出【独占整行】的技能 marker;其余行保留(防误吞正文)。
  const skills: string[] = []
  const kept: string[] = []
  for (const line of normalized.split("\n")) {
    const sm = SKILL_LINE.exec(line.trim())
    if (sm) skills.push(sm[1].trim())
    else kept.push(line)
  }
  const hadSkill = skills.length > 0
  // 有 skill:用去掉 skill 行的文本(折叠剥离后多余空行);无 skill:保持原 text(既有"无 marker 原样"语义)。
  const work = hadSkill ? kept.join("\n").replace(/\n{3,}/g, "\n\n").trim() : normalized
  const fallbackBody = hadSkill ? work : text
  // 2. 附件解析(逻辑不变,on work)
  const m = MARKER_RE.exec(work)
  if (!m || m.index === undefined) return { body: fallbackBody, attachments: [], skills }
  const lines = work
    .slice(m.index + m[0].length)
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
  // 每行必须是工作区路径,或(多段附件时残留的)另一个 marker——混入其它文本即视为用户正文。
  if (!lines.length || !lines.every((l) => WORKSPACE_PATH.test(l) || MARKER_LINE.test(l))) {
    return { body: fallbackBody, attachments: [], skills }
  }
  const attachments = lines.filter((l) => WORKSPACE_PATH.test(l))
  if (!attachments.length) return { body: fallbackBody, attachments: [], skills }
  return { body: work.slice(0, m.index).trim(), attachments, skills }
}
