import type { ReactNode } from "react"

// 一组设置:可选低对比小标题 + 软边框圆角卡(行间细分隔线)。
export function SettingGroup({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      {label && (
        <div className="px-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
          {label}
        </div>
      )}
      {/* 不用 overflow-hidden 收圆角:行本身无背景,裁剪反而会把行内浮层(ModelMenu/SelectMenu)切残 */}
      <div className="divide-y divide-slate-100 rounded-xl border border-slate-200/80 bg-white">
        {children}
      </div>
    </section>
  )
}
