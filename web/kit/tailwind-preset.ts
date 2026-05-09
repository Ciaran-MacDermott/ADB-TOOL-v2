// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
import type { Config } from "tailwindcss";

const preset: Partial<Config> = {
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#F5F0FA",
          100: "#E8DBF2",
          200: "#D2BAE5",
          300: "#B594D2",
          400: "#8B5DAF",
          500: "#6A1A94",
          600: "#4E106F",
          700: "#3A0D54",
          800: "#2E0840",
          900: "#1F052B",
        },
        ok:   "#059669",
        okd:  "#047857",
        warn: "#D97706",
        err:  "#DC2626",
        edit: "#F3E8FF",
        ink: {
          1: "#0F172A",
          2: "#334155",
          3: "#64748B",
        },
      },
      fontFamily: {
        sans: [
          "var(--font-inter)",
          "Inter",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      borderRadius: {
        btn: "0.5rem",
        card: "1rem",
        "card-lg": "1.25rem",
      },
      boxShadow: {
        card: "0 1px 0 rgba(15, 23, 42, 0.02), 0 6px 24px -12px rgba(15, 23, 42, 0.10)",
        "card-hover": "0 4px 16px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04)",
        "btn-primary": "0 1px 2px rgba(78, 16, 111, 0.20), inset 0 1px 0 rgba(255,255,255,0.10)",
        "btn-success": "0 1px 2px rgba(5, 150, 105, 0.18), inset 0 1px 0 rgba(255,255,255,0.10)",
      },
      transitionTimingFunction: {
        "out-soft": "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
};

export default preset;