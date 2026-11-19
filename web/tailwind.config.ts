import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff", 100: "#dbe6ff", 200: "#bcd0ff", 500: "#2f5bd8", 600: "#1f45b8",
          700: "#173693", 800: "#122a73", 900: "#0c1d52",
        },
        accent: { 400: "#fb923c", 500: "#f97316", 600: "#ea580c" },
        surface: "#f4f6fa",
      },
      fontFamily: { sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.06), 0 2px 8px rgba(16,24,40,.06)" },
      borderRadius: { xl2: "1.1rem" },
    },
  },
  plugins: [],
} satisfies Config;
