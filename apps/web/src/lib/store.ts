import { create } from "zustand";

import type { AppStatus } from "../api/types";
import { TERMINAL_STATUSES } from "../api/types";

export type ViewName = "board" | "table" | "timeline" | "insights";

interface UiState {
  view: ViewName;
  drawerId: string | null;
  query: string;
  collapsed: Record<string, boolean>;
  toast: { message: string; tone: "info" | "error" } | null;

  setView: (view: ViewName) => void;
  openDrawer: (id: string) => void;
  closeDrawer: () => void;
  setQuery: (query: string) => void;
  toggleColumn: (status: AppStatus) => void;
  notify: (message: string, tone?: "info" | "error") => void;
  dismissToast: () => void;
}

/** Server data lives in TanStack Query; this store is only UI state. */
export const useUi = create<UiState>((set) => ({
  view: "board",
  drawerId: null,
  query: "",
  // Terminal columns start collapsed — they're the biggest and the least useful,
  // and letting them dominate the board is demoralising (README §7.1).
  collapsed: Object.fromEntries(TERMINAL_STATUSES.map((status) => [status, true])),
  toast: null,

  setView: (view) => set({ view }),
  openDrawer: (drawerId) => set({ drawerId }),
  closeDrawer: () => set({ drawerId: null }),
  setQuery: (query) => set({ query }),
  toggleColumn: (status) =>
    set((state) => ({ collapsed: { ...state.collapsed, [status]: !state.collapsed[status] } })),
  notify: (message, tone = "info") => set({ toast: { message, tone } }),
  dismissToast: () => set({ toast: null }),
}));
