import type { Config } from "tailwindcss";

/** Build a Tailwind colour that reads a CSS-var token and supports opacity. */
const token = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    // Pixel form language (2026-07 reskin): the whole app squares off and
    // drops soft blur for hard-offset "pixel-step" shadows. Overriding the
    // scales here (not `extend`) retunes every existing rounded-*/shadow-*
    // usage in one place.
    borderRadius: {
      none: "0",
      sm: "0",
      DEFAULT: "0",
      md: "0",
      lg: "0",
      xl: "0",
      "2xl": "0",
      "3xl": "0",
      full: "0",
    },
    boxShadow: {
      sm: "2px 2px 0 rgb(var(--shadow) / 0.55)",
      DEFAULT: "2px 2px 0 rgb(var(--shadow) / 0.55)",
      md: "3px 3px 0 rgb(var(--shadow) / 0.55)",
      lg: "4px 4px 0 rgb(var(--shadow) / 0.6)",
      xl: "5px 5px 0 rgb(var(--shadow) / 0.6)",
      "2xl": "6px 6px 0 rgb(var(--shadow) / 0.65)",
      inner: "inset 2px 2px 0 rgb(var(--shadow) / 0.35)",
      none: "none",
    },
    extend: {
      fontFamily: {
        sans: ['"Pixelify Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"VT323"', "ui-monospace", "monospace"],
        display: ['"Silkscreen"', "monospace"],
      },
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
