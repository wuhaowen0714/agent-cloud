import { splitBreadcrumb } from "../../files"

export function FileBreadcrumb({ path, onNavigate }: { path: string; onNavigate: (p: string) => void }) {
  const crumbs = splitBreadcrumb(path)
  return (
    <div className="flex flex-wrap items-center gap-1 border-b border-slate-100 px-3 py-1.5 text-xs text-slate-500">
      {crumbs.map((c, i) => (
        <span key={c.path} className="flex items-center gap-1">
          {i > 0 && <span className="text-slate-300">/</span>}
          <button
            className={i === crumbs.length - 1 ? "text-slate-700" : "hover:text-brand-600"}
            onClick={() => onNavigate(c.path)}
          >
            {c.name}
          </button>
        </span>
      ))}
    </div>
  )
}
