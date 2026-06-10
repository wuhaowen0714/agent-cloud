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

describe("Markdown 语法高亮", () => {
  it("带语言标注的代码块产出 hljs token span", () => {
    const { container } = render(
      <Markdown>{"```python\ndef f():\n    return 'hi'\n```"}</Markdown>,
    )
    expect(container.querySelector("pre code.hljs")).not.toBeNull()
    expect(container.querySelector("pre code .hljs-keyword")).not.toBeNull() // def/return
    expect(container.querySelector("pre code .hljs-string")).not.toBeNull() // 'hi'
  })

  it("无语言标注的代码块保持纯文本(不做自动探测)", () => {
    const { container } = render(<Markdown>{"```\nplain text here\n```"}</Markdown>)
    expect(container.querySelector("pre code [class^='hljs-']")).toBeNull()
  })

  it("行内 code 不受高亮影响", () => {
    const { container } = render(<Markdown>{"前缀 `def x` 后缀"}</Markdown>)
    expect(container.querySelector("p > code .hljs-keyword")).toBeNull()
  })
})
