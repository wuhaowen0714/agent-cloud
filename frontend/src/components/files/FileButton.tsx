import { useStore } from "../../store"

export function FileButton() {
  const toggle = useStore((s) => s.toggleFileDrawer)
  const userId = useStore((s) => s.userId)
  if (!userId) return null
  return (
    <button
      className="flex items-center gap-1.5 rounded border border-slate-200 px-2 py-1 text-sm text-slate-600 hover:bg-slate-50"
      onClick={toggle}
    >
      📁 文件
    </button>
  )
}
