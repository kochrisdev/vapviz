import type { Config } from "tailwindcss";

/** Build a Tailwind colour that reads a CSS-var token and supports opacity. */
const token = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("--bg"),
        surface: {
          DEFAULT: token("--surface"),
          hover: token("--surface-hover"),
          inset: token("--surface-inset"),
        },
        border: {
          DEFAULT: token("--border"),
          strong: token("--border-strong"),
        },
        content: {
          DEFAULT: token("--content"),
          muted: token("--content-muted"),
          faint: token("--content-faint"),
          "on-accent": token("--content-on-accent"),
        },
        accent: {
          DEFAULT: token("--accent"),
          hover: token("--accent-hover"),
        },
        kind: {
          agent: token("--kind-agent"),
          step: token("--kind-step"),
          tool: token("--kind-tool"),
          llm: token("--kind-llm"),
        },
        status: {
          pending: token("--status-pending"),
          running: token("--status-running"),
          success: token("--status-success"),
          error: token("--status-error"),
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
