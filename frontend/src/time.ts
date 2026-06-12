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

// 会话列表时间分组:按本地日历日距今天数分档。未来(时钟偏差)归今天;坏值归更早。
export function timeGroupLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "更早"
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((startOf(now) - startOf(d)) / 86_400_000)
  if (days <= 0) return "今天"
  if (days === 1) return "昨天"
  if (days <= 7) return "前 7 天"
  if (days <= 30) return "前 30 天"
  return "更早"
}
