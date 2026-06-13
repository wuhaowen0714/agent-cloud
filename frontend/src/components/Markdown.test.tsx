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

describe("Markdown 数学公式(KaTeX)", () => {
  it("LLM 风格 \\( … \\) 行内公式渲染成 KaTeX(而非裸文本 ( )", () => {
    const { container } = render(<Markdown>{"频率 \\( \\delta = \\sqrt{2\\eta} \\) 判据"}</Markdown>)
    expect(container.querySelector(".katex")).not.toBeNull() // 已渲染成 KaTeX
    expect(container.textContent).toContain("判据") // 周围文本保留
    // 定界符 \( 被归一化吃掉,没漏成裸文本(KaTeX 的 MathML annotation 仍含源 \delta,属正常)
    expect(container.querySelector("p")?.textContent).not.toContain("\\(")
  })

  it("LLM 风格 \\[ … \\] 独占段落渲染成 KaTeX display", () => {
    const { container } = render(<Markdown>{"\\[ \\tilde{k}(\\omega) \\to k_0 \\]"}</Markdown>)
    expect(container.querySelector(".katex-display")).not.toBeNull()
  })

  it("原生 $ … $ 也渲染(remark-math 默认定界符)", () => {
    const { container } = render(<Markdown>{"质能 $E = mc^2$ 方程"}</Markdown>)
    expect(container.querySelector(".katex")).not.toBeNull()
  })

  it("普通括号文本不被误当公式", () => {
    const { container } = render(<Markdown>{"这是(普通中文括号)和 (english parens)。"}</Markdown>)
    expect(container.querySelector(".katex")).toBeNull()
    expect(container.textContent).toContain("(english parens)")
  })
})
