import type { Config } from "tailwindcss";

/**
 * Live Market frontend uses the same token palette as the parent app's
 * Live mode (light theme). Tokens are defined in `src/index.css` so we
 * can keep a consistent visual identity across both deployments.
 */
const tokenColor = (name: string) =>
  `rgb(var(--color-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: tokenColor("bg"),
          surface: tokenColor("bg-surface"),
          elevated: tokenColor("bg-elevated"),
        },
        border: {
          DEFAULT: tokenColor("border"),
          strong: tokenColor("border-strong"),
        },
        fg: {
          DEFAULT: tokenColor("fg"),
          muted: tokenColor("fg-muted"),
          subtle: tokenColor("fg-subtle"),
        },
        accent: {
          green: tokenColor("accent-green"),
          red: tokenColor("accent-red"),
          amber: tokenColor("accent-amber"),
          blue: tokenColor("accent-blue"),
          violet: tokenColor("accent-violet"),
          cyan: tokenColor("accent-cyan"),
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 0 rgb(var(--color-card-inset) / 0.04) inset, 0 1px 2px rgb(0 0 0 / 0.1)",
      },
    },
  },
  plugins: [],
} satisfies Config;
