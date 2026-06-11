# 聊天滚动:粘底跟随 设计

**日期:** 2026-06-11
**状态:** 设计已批准

## 目标

修复流式生成期间无条件 `scrollIntoView` 把用户拽回底部的缺陷:在底部才跟随,上翻即停,提供「回到底部」浮钮。

## 设计(全部在 `MessageList.tsx` + 新纯函数)

- **`isNearBottom(el, threshold=40)`**(新 `frontend/src/scroll.ts`):`el.scrollHeight - el.scrollTop - el.clientHeight < threshold`。纯函数,jsdom 里 mock 几何即可测。
- **跟随状态**:滚动容器(现 `overflow-auto` div)挂 `ref` + `onScroll`;`followRef = useRef(true)` 存权威值(effect 读它,不触发渲染);`atBottom` state 仅驱动浮钮显隐,**边界翻转才 setState**(滚动事件高频)。
- **自动滚动 effect**(替换现 `useEffect`):`if (followRef.current) endRef.current?.scrollIntoView()` —— `behavior` 从 `"smooth"` 改为默认(即时):平滑动画在高频 delta 下排队,是"拽走"感的帮凶;依赖数组 `[messages, live]` 不变。
- **强制回底两时机**:用户发送(`MessageList` 暴露不出发送事件——由 props 驱动:live 从 null→非 null 且 `userText` 非空时置 follow=true 并滚底;实现上用 `live?.userText` 的变化判)与切会话(`messages` 引用全换/sessionId 变化——MessageList 不知 sessionId,以 `live===null && messages` 重置?简化:**组件内监听 `live?.sessionId + live?.userText` 成对变化置 follow=true**;切会话时 MessageList 因 messages 换源重渲染,且 store.setSession 清 live → 新会话首次 live 或 messages 加载即按 followRef 初值…切会话重置用 key 更稳)。
  - **落地选择**:ChatView 给 `MessageList` 加 `key={sessionId}`(切会话整组件重建,follow 回到初值 true,滚动位置自然重置);发送强制回底在 MessageList 内监听「`live` 由空变为带 `userText` 的对象」→ `followRef.current = true` + 滚底。
- **「↓」浮钮**:`!atBottom` 时显示;绝对定位在消息区右下(MessageList 外层包 `relative`),圆形、`ChevronDown`(lucide)、白底描边阴影;点击 → `scrollIntoView` 到底(onScroll 随之恢复 follow)。`aria-label="回到底部"`。
- 程序性滚动也触发 onScroll → 几何已在底 → follow 保持/恢复,无需特判。

## 非目标(YAGNI)

- 不做"新消息"计数徽标;不做位置记忆(切回会话恢复上次滚动位);不动 turn_done 后的历史刷新逻辑。

## 测试(jsdom:`scrollIntoView = vi.fn()` 原型桩;容器几何 `Object.defineProperty`)

- `isNearBottom`:阈值内/外、恰好相等。
- 在底部(默认):live 更新 → `scrollIntoView` 被调。
- 模拟上翻(改容器几何 + fire scroll)后:live 更新 → **不**滚动;「回到底部」按钮出现。
- 点按钮 → `scrollIntoView` 调用且(fire scroll 回到底部几何后)按钮消失。
- 发送强制回底:live 从 null → 带 userText → 即使此前上翻也滚底。
