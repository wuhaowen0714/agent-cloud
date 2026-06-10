export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB", "TB"]
  let v = bytes / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`
}

export interface Crumb { name: string; path: string }
export function splitBreadcrumb(path: string): Crumb[] {
  const crumbs: Crumb[] = [{ name: "工作区", path: "" }]
  let acc = ""
  for (const p of path.split("/").filter(Boolean)) {
    acc = acc ? `${acc}/${p}` : p
    crumbs.push({ name: p, path: acc })
  }
  return crumbs
}

const IMG = new Set(["png", "jpg", "jpeg", "gif", "svg", "webp"])
const MD = new Set(["md", "markdown"])
const HTML = new Set(["html", "htm"])
const TEXT_MAX = 1024 * 1024 // 1 MB:超过只给下载
export type PreviewKind = "image" | "text" | "markdown" | "html" | "download"
export function previewKind(entry: { name: string; size: number }): PreviewKind {
  const ext = entry.name.split(".").pop()?.toLowerCase() ?? ""
  if (IMG.has(ext)) return "image"
  if (entry.size > TEXT_MAX) return "download"
  if (MD.has(ext)) return "markdown" // 渲染展示(可切源码)
  if (HTML.has(ext)) return "html" // 沙箱 iframe 渲染(可切源码)
  return "text"
}
