import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it } from "vitest"
import { useStore } from "../../store"
import { SkillsPanel } from "./SkillsPanel"

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>

describe("SkillsPanel", () => {
  beforeEach(() => useStore.setState({ userId: "u1" }))

  it("renders the installed + install sections", () => {
    render(wrap(<SkillsPanel />))
    expect(screen.getByText("已安装")).toBeInTheDocument()
    expect(screen.getByText("从 registry 安装")).toBeInTheDocument()
  })
})
