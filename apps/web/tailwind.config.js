/** @type {import('tailwindcss').Config} */

// Every colour is a CSS variable holding "r g b" channels, so `bg-surface/50` still
// works and switching dimension (Overworld / Nether / End) is one attribute on <html>.
// The values live in src/index.css.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    // Blocks don't have rounded corners. `full` survives for the odd status dot.
    borderRadius: {
      none: "0",
      sm: "0",
      DEFAULT: "0",
      md: "0",
      lg: "0",
      xl: "0",
      "2xl": "0",
      full: "9999px",
    },
    extend: {
      colors: {
        // One accent, one surface ramp — card density is the whole point of a board,
        // so status is carried by column position and text, never by colour alone.
        surface: {
          DEFAULT: token("surface"),
          raised: token("surface-raised"),
          card: token("surface-card"),
          border: token("surface-border"),
        },
        accent: {
          DEFAULT: token("accent"),
          muted: token("accent-muted"),
          // Accent as text on a dark surface; the fill is too dark to read as type.
          ink: token("accent-ink"),
        },
        "on-accent": token("on-accent"),
        stale: { warn: token("warn"), dim: token("dim") },
        // Text ink. Overriding the slate steps re-themes every `text-slate-*` at once.
        slate: {
          100: token("ink-100"),
          200: token("ink-200"),
          300: token("ink-300"),
          400: token("ink-400"),
          500: token("ink-500"),
          600: token("ink-600"),
          900: token("ink-900"),
        },
        chart: {
          stage: token("chart-stage"),
          offer: token("chart-offer"),
          reject: token("chart-reject"),
          neutral: token("chart-neutral"),
        },
        block: {
          0: token("block-0"),
          1: token("block-1"),
          2: token("block-2"),
          3: token("block-3"),
          4: token("block-4"),
        },
        xp: { DEFAULT: "#80d825", track: "#1c1c1c", ink: "#80ff20" },
      },
      fontFamily: {
        sans: ["var(--font-body)"],
      },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        blink: { "50%": { opacity: "0" } },
        splash: {
          "0%, 100%": { transform: "rotate(-15deg) scale(1)" },
          "50%": { transform: "rotate(-15deg) scale(1.08)" },
        },
      },
      animation: {
        "fade-in": "fade-in 180ms ease-out",
        shimmer: "shimmer 1.4s infinite",
        blink: "blink 1s steps(1) infinite",
        splash: "splash 0.9s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
