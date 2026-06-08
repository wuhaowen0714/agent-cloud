import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it } from "vitest"
import { useStore } from "../../store"
import { AgentSettings } from "./AgentSettings"

const wrap = (ui: ReactNode) => <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>

describe("AgentSettings", () => {
  beforeEach(() => useStore.setState({ userId: "u1", agentId: null }))

  it("shows the create form when no agent is selected", () => {
    render(wrap(<AgentSettings />))
    expect(screen.getByText("新建 Agent")).toBeInTheDocument()
    expect(screen.getByText("创建")).toBeInTheDocument()
  })
})
