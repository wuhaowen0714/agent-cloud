// composer @ 文件引用的纯函数(spec 2026-06-10-file-ref-design):
// 由「文本 + 光标」派生当前 @ 词,再对文件索引做子串过滤。无 DOM/状态依赖,可单测。

export interface AtToken {
  start: number // "@" 在 text 中的下标(替换区间 [start, caret) 的左端)
  query: string // "@" 之后到光标的内容(过滤词;兼容中文)
}

// 光标所在词以 "@" 开头才算引用词。向左扫到空白/行首即词首——天然保证 "@" 前是
// 空白或文本开头(邮箱 a@b 的词首是 "a",不触发)。词内再次出现 "@"(如 @a@b)
// 视为放弃引用。光标恰在 "@" 前(caret === start)属于词外,不触发。
export function atTokenAt(text: string, caret: number): AtToken | null {
  let start = caret
  while (start > 0 && !/\s/.test(text.charAt(start - 1))) start--
  if (caret <= start || text.charAt(start) !== "@") return null
  const query = text.slice(start + 1, caret)
  return query.includes("@") ? null : { start, query }
}

// 不区分大小写的子串匹配(路径任意位置,目录名也能命中),保序截断到 max。
export function filterPaths(paths: string[], query: string, max = 20): string[] {
  const q = query.toLowerCase()
  const out: string[] = []
  for (const p of paths) {
    if (p.toLowerCase().includes(q)) {
      out.push(p)
      if (out.length >= max) break
    }
  }
  return out
}
