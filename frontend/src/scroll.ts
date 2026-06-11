// 粘底跟随的判定:距底小于阈值视为「在底部」。阈值给亚像素滚动与回弹留余量;
// 结构化参数(而非 HTMLElement)让 jsdom 测试只 mock 三个数字。
export function isNearBottom(
  el: { scrollHeight: number; scrollTop: number; clientHeight: number },
  threshold = 40,
): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < threshold
}
