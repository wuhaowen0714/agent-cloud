// 消息时间戳:与「现在」同日只给时分;同年给 月-日 时:分;跨年给全量。本地时区,24h 制。
// now 可注入仅为测试确定性;生产调用走默认值。
export function fmtTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "" // 坏值不上屏 NaN(正常通路 DB/Pydantic 已保证非空合法)
  const p = (n: number) => String(n).padStart(2, "0")
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) return hm
  const md = `${p(d.getMonth() + 1)}-${p(d.getDate())}`
  if (d.getFullYear() === now.getFullYear()) return `${md} ${hm}`
  return `${d.getFullYear()}-${md} ${hm}`
}
