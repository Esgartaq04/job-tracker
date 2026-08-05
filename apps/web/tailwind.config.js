/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // One accent, one surface ramp — card density is the whole point of a board,
        // so status is carried by column position and text, never by colour alone.
        surface: {
          DEFAULT: "#0b1120",
          raised: "#131c31",
          card: "#1a2440",
          border: "#26324f",
        },
        accent: { DEFAULT: "#6366f1", muted: "#4f46e5" },
        stale: { warn: "#f59e0b", dim: "#64748b" },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "fade-in": "fade-in 180ms ease-out",
        shimmer: "shimmer 1.4s infinite",
      },
    },
  },
  plugins: [],
};
