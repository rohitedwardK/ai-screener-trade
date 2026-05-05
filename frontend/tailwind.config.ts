import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0b0e14",
          surface: "#11161f",
          elevated: "#161c27",
        },
        border: {
          DEFAULT: "#232a36",
          strong: "#2e3848",
        },
        fg: {
          DEFAULT: "#e6e9ef",
          muted: "#8b94a7",
          subtle: "#5b6478",
        },
        accent: {
          green: "#10b981",
          red: "#ef4444",
          amber: "#f59e0b",
          blue: "#3b82f6",
          violet: "#8b5cf6",
          cyan: "#06b6d4",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 1px 2px rgba(0,0,0,0.4)",
      },
    },
  },
  plugins: [],
} satisfies Config;
