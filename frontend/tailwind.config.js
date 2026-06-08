import typography from "@tailwindcss/typography"

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f0fdfa",
          100: "#ccfbf1",
          200: "#99f6e4",
          300: "#5eead4",
          400: "#2dd4bf",
          500: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
          800: "#115e59",
          900: "#134e4a",
        },
      },
      boxShadow: {
        // 柔和卡片阴影 + popover 悬浮阴影,撑起「有质感」的层次
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
        pop: "0 10px 34px -10px rgb(15 23 42 / 0.22), 0 2px 6px -2px rgb(15 23 42 / 0.08)",
        focus: "0 0 0 3px rgb(20 184 166 / 0.15)",
      },
    },
  },
  plugins: [typography],
}
