import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Speedo red
        brand: {
          50: "#fef2f2", 100: "#fee2e2", 200: "#fecaca", 500: "#e02424", 600: "#c81e1e",
          700: "#b91c1c", 800: "#991b1b", 900: "#7f1d1d",
        },
        accent: { 400: "#fbbf24", 500: "#f59e0b", 600: "#d97706" },
        surface: "#f4f6fa",
      },
      fontFamily: { sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.06), 0 2px 8px rgba(16,24,40,.06)" },
      borderRadius: { xl2: "1.1rem" },
    },
  },
  plugins: [],
} satisfies Config;
