import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { Markdown } from "./Markdown"

describe("Markdown 代码块对比度", () => {
  it("包装类含 [&_pre_code]:text-inherit(防行内 code 颜色泄漏进深色代码块)", () => {
    const { container } = render(<Markdown>{"```\nconst x = 1\n```"}</Markdown>)
    const wrapper = container.firstElementChild as HTMLElement
    expect(wrapper.className).toContain("[&_pre_code]:text-inherit")
    expect(container.querySelector("pre code")).not.toBeNull()
  })
})
