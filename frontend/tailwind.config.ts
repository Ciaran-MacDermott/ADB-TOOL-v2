import type { Config } from "tailwindcss";
import circanaPreset from "./kit/tailwind-preset";

const config: Config = {
  presets: [circanaPreset as Config],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./kit/**/*.{ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};

export default config;
