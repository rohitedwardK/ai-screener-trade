import type { Config } from "tailwindcss";

/**
 * Tailwind tokens are routed through CSS custom properties so the same utility
 * (e.g. `bg-bg-surface`, `text-fg`, `border-accent-blue`) renders correctly
 * in both Historical (dark) and Live (light) modes. The actual color values
 * live in `src/index.css` under `:root` (light) and `.dark` (current dark).
 *
 * The `<alpha-value>` placeholder is replaced by Tailwind so opacity utilities
 * like `bg-accent-blue/15` keep working unchanged.
 */
const tokenColor = (name: string) =>
  `rgb(var(--color-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
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
        card: "0 1px 0 0 rgb(var(--color-card-inset) / 0.04) inset, 0 1px 2px rgb(0 0 0 / 0.4)",
      },
    },
  },
  plugins: [],
} satisfies Config;
