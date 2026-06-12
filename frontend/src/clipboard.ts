/** 复制文本到剪贴板,返回是否成功。
 *
 * Clipboard API(navigator.clipboard)只在安全上下文(HTTPS / localhost)存在——
 * 生产是 http://公网IP:8080,API 直接为 undefined,之前的 `?.writeText` 静默没效果。
 * 故优先走现代 API,不存在或被拒时退回旧的 document.execCommand("copy")
 * (经临时 textarea;deprecated 但各浏览器保留,且不受安全上下文限制)。 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 安全上下文里也可能被权限策略拒 → 继续试老路
    }
  }
  const prev = document.activeElement // 记下焦点:select 会夺焦,完事还回去(别打断正在输入的人)
  const ta = document.createElement("textarea")
  ta.value = text
  ta.setAttribute("readonly", "") // 防移动端弹键盘
  // 钉在视口外:不挤布局、不闪滚动条
  ta.style.position = "fixed"
  ta.style.top = "0"
  ta.style.left = "-9999px"
  document.body.appendChild(ta)
  // Firefox 的 select() 不隐式移焦点,而 execCommand("copy") 取的是焦点处选区 → 必须显式 focus;
  // setSelectionRange 兜 Safari 对 readonly textarea 的 select() 怪癖。
  ta.focus({ preventScroll: true })
  ta.select()
  ta.setSelectionRange(0, ta.value.length)
  let ok = false
  try {
    ok = document.execCommand("copy")
  } catch {
    ok = false
  } finally {
    ta.remove()
    if (prev instanceof HTMLElement) prev.focus({ preventScroll: true })
  }
  return ok
}
