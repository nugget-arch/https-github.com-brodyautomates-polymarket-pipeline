import type { Config } from "tailwindcss";

// Dark, dense, professional. Green = positive, red = negative, blue = info.
// Original design; does not copy any third-party brand/logo/identity.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0e14",
        panel: "#141924",
        panel2: "#1b2230",
        border: "#232b3a",
        muted: "#8b97ad",
        pos: "#22c55e",
        neg: "#ef4444",
        info: "#3b82f6",
        warn: "#f59e0b",
      },
    },
  },
  plugins: [],
};
export default config;
