import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"
import type { FileEntry } from "../../types"
import { FileList } from "./FileList"

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
const dir: FileEntry = { name: "src", path: "src", is_dir: true, size: 0, mtime: 0 }
const file: FileEntry = { name: "a.txt", path: "a.txt", is_dir: false, size: 2048, mtime: 0 }

describe("FileList", () => {
  it("opens a directory vs previews a file, and shows file size", () => {
    const onOpenDir = vi.fn()
    const onPreview = vi.fn()
    render(
      wrap(
        <FileList
          entries={[dir, file]}
          onOpenDir={onOpenDir}
          onPreview={onPreview}
          onChanged={() => {}}
        />,
      ),
    )
    expect(screen.getByText("2.0 KB")).toBeInTheDocument()
    fireEvent.click(screen.getByText("src"))
    expect(onOpenDir).toHaveBeenCalledWith(dir)
    fireEvent.click(screen.getByText("a.txt"))
    expect(onPreview).toHaveBeenCalledWith(file)
  })

  it("shows empty state", () => {
    render(
      wrap(<FileList entries={[]} onOpenDir={() => {}} onPreview={() => {}} onChanged={() => {}} />),
    )
    expect(screen.getByText("空目录")).toBeInTheDocument()
  })

  // 沙箱把 HOME/pip/npm 缓存、技能物化目录路由进工作区(.home/.npm-global/.skills),
  // 对用户是基础设施噪音 → 点开头【目录】不显示;点【文件】(.env.example 等)是用户
  // 内容,保持可见可管理(与后端 @ 索引剪枝政策一致:剪点目录、留点文件)。
  it("hides dot-directories but keeps dot-files visible", () => {
    const hiddenDir: FileEntry = { name: ".home", path: ".home", is_dir: true, size: 0, mtime: 0 }
    const dotFile: FileEntry = { name: ".env", path: ".env", is_dir: false, size: 5, mtime: 0 }
    render(
      wrap(
        <FileList
          entries={[hiddenDir, dotFile, file]}
          onOpenDir={() => {}}
          onPreview={() => {}}
          onChanged={() => {}}
        />,
      ),
    )
    expect(screen.queryByText(".home")).not.toBeInTheDocument()
    expect(screen.getByText(".env")).toBeInTheDocument()
    expect(screen.getByText("a.txt")).toBeInTheDocument()
  })

  it("dir with only hidden entries renders empty state", () => {
    const hiddenDir: FileEntry = { name: ".git", path: ".git", is_dir: true, size: 0, mtime: 0 }
    render(
      wrap(
        <FileList entries={[hiddenDir]} onOpenDir={() => {}} onPreview={() => {}} onChanged={() => {}} />,
      ),
    )
    expect(screen.getByText("空目录")).toBeInTheDocument()
  })

  it("renaming a dir to dot-name is blocked (would vanish from UI)", () => {
    vi.spyOn(window, "prompt").mockReturnValue(".secret")
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {})
    render(
      wrap(<FileList entries={[dir]} onOpenDir={() => {}} onPreview={() => {}} onChanged={() => {}} />),
    )
    fireEvent.click(screen.getByText("重命名"))
    expect(alertSpy).toHaveBeenCalled()
    vi.restoreAllMocks()
  })
})
