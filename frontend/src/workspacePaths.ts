// 聊天正文里的工作区路径识别(inline code → 可点击链接)。只认「文件索引里真实存在」的
// 路径,不做猜测:精确路径 → 文件;某些条目的目录前缀 → 目录;裸文件名(不含 /)在全工作区
// 唯一 → 该文件;其余(多义/不存在/外部 URL)一律不链接,绝不误伤普通代码片段。
export interface PathHit {
  path: string
  isDir: boolean
}

export function resolveWorkspacePath(raw: string, index: string[]): PathHit | null {
  const text = raw.trim()
  if (!text || text.length > 200) return null
  if (/\s/.test(text)) return null // 工作区路径按约定无空白;含空白的多半是普通代码
  if (/^[a-z]+:\/\//i.test(text) || text.startsWith("/")) return null // 外部 URL / 绝对路径
  const p = text.replace(/\/+$/, "") // 目录写法 documents/x/ 去尾斜杠归一
  if (!p) return null
  if (index.includes(p)) return { path: p, isDir: false }
  const prefix = `${p}/`
  if (index.some((f) => f.startsWith(prefix))) return { path: p, isDir: true }
  if (!p.includes("/")) {
    // 裸文件名:全工作区唯一才链接(README.md 到处都有时宁可不链,不跳错)
    const matches = index.filter((f) => f === p || f.endsWith(`/${p}`))
    if (matches.length === 1) return { path: matches[0], isDir: false }
  }
  return null
}
