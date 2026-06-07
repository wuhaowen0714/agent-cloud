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
          userId="u1"
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
      wrap(<FileList entries={[]} userId="u1" onOpenDir={() => {}} onPreview={() => {}} onChanged={() => {}} />),
    )
    expect(screen.getByText("空目录")).toBeInTheDocument()
  })
})
