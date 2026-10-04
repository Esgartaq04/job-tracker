import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

export const DIMENSIONS = ["overworld", "nether", "end"] as const;
export type Dimension = (typeof DIMENSIONS)[number];

export const DIMENSION_LABELS: Record<Dimension, string> = {
  overworld: "Overworld",
  nether: "Nether",
  end: "The End",
};

/** Browser chrome colour per dimension — matches `--surface` in index.css. */
export const THEME_COLORS: Record<Dimension, string> = {
  overworld: "#1c1611",
  nether: "#160707",
  end: "#0c0912",
};

/** Also read by the inline script in index.html, which applies prefs before first paint. */
export const PREFS_KEY = "job-tracker:prefs";

interface PrefsState {
  dimension: Dimension;
  pixelFont: boolean;
  /** Applications per week the XP bar fills towards. */
  weeklyGoal: number;

  setDimension: (dimension: Dimension) => void;
  togglePixelFont: () => void;
  setWeeklyGoal: (goal: number) => void;
}

// Storage can be missing or throw (private windows, blocked site data). Preferences
// are a convenience, so a failure just means the defaults.
const safeStorage: StateStorage = {
  getItem: (name) => {
    try {
      return localStorage.getItem(name);
    } catch {
      return null;
    }
  },
  setItem: (name, value) => {
    try {
      localStorage.setItem(name, value);
    } catch {
      // Not persisted this time; the in-memory value still applies.
    }
  },
  removeItem: (name) => {
    try {
      localStorage.removeItem(name);
    } catch {
      // Nothing to clean up.
    }
  },
};

/** Per-device look-and-feel. Unlike `useUi`, this survives a reload. */
export const usePrefs = create<PrefsState>()(
  persist(
    (set) => ({
      dimension: "overworld",
      pixelFont: true,
      weeklyGoal: 10,

      setDimension: (dimension) => set({ dimension }),
      togglePixelFont: () => set((state) => ({ pixelFont: !state.pixelFont })),
      setWeeklyGoal: (goal) => set({ weeklyGoal: Math.min(99, Math.max(1, Math.round(goal))) }),
    }),
    {
      name: PREFS_KEY,
      storage: createJSONStorage(() => safeStorage),
      partialize: ({ dimension, pixelFont, weeklyGoal }) => ({ dimension, pixelFont, weeklyGoal }),
    },
  ),
);

/** Mirror the prefs onto <html> so the CSS variables and font switch. */
export function applyPrefs(dimension: Dimension, pixelFont: boolean) {
  const root = document.documentElement;
  root.dataset.dimension = dimension;
  root.dataset.font = pixelFont ? "pixel" : "clean";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[dimension]);
}
