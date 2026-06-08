import "@testing-library/jest-dom"

// jsdom 未实现 scrollIntoView;组件(如 MessageList)在 effect 里会调用它。
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
