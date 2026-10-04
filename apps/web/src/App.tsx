import { useEffect, useState } from "react";

import { getToken } from "./api/client";
import { useServerEvents } from "./api/events";
import { AccountMenu } from "./features/auth/AccountMenu";
import { SignIn } from "./features/auth/SignIn";
import { Board } from "./features/board/Board";
import { MobileBoard } from "./features/board/MobileBoard";
import { Drawer } from "./features/detail/Drawer";
import { Insights } from "./features/insights/Insights";
import { QuickAdd } from "./features/quickadd/QuickAdd";
import { QuickAddSheet } from "./features/quickadd/QuickAddSheet";
import { NeedsAttention } from "./features/reminders/NeedsAttention";
import { TableView } from "./features/table/TableView";
import { DimensionSwitcher } from "./features/theme/DimensionSwitcher";
import { applyPrefs, usePrefs } from "./lib/prefs";
import { useUi, type ViewName } from "./lib/store";
import { MOBILE_QUERY, useMediaQuery } from "./lib/useMediaQuery";

const VIEWS: ViewName[] = ["board", "table", "insights"];

export function App() {
  const [signedIn, setSignedIn] = useState(() => Boolean(getToken()));
  const view = useUi((state) => state.view);
  const setView = useUi((state) => state.setView);
  const query = useUi((state) => state.query);
  const setQuery = useUi((state) => state.setQuery);
  const toast = useUi((state) => state.toast);
  const isMobile = useMediaQuery(MOBILE_QUERY);
  const dismissToast = useUi((state) => state.dismissToast);
  const dimension = usePrefs((state) => state.dimension);
  const pixelFont = usePrefs((state) => state.pixelFont);

  useServerEvents(signedIn);

  useEffect(() => applyPrefs(dimension, pixelFont), [dimension, pixelFont]);

  useEffect(() => {
    const onSignedOut = () => setSignedIn(false);
    window.addEventListener("job-tracker:signed-out", onSignedOut);
    return () => window.removeEventListener("job-tracker:signed-out", onSignedOut);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(dismissToast, 4000);
    return () => clearTimeout(timer);
  }, [toast, dismissToast]);

  if (!signedIn) return <SignIn onSignedIn={() => setSignedIn(true)} />;

  return (
    <div className="mc-world flex h-full flex-col text-slate-100">
      <header className="flex items-center gap-3 border-b-2 border-black/80 bg-surface-raised/90 px-4 py-2.5">
        <span className="mc-shadow whitespace-nowrap text-sm font-bold text-slate-100">⛏ Tracker</span>
        {/* The persistent URL bar is a desktop affordance; on mobile it's the FAB. */}
        <div className="hidden flex-1 md:flex">
          <QuickAdd />
        </div>
        <div className="flex-1 md:hidden" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search…"
          aria-label="Search applications"
          className="mc-slot hidden w-40 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none md:block"
        />
        <DimensionSwitcher />
        <AccountMenu onSignOut={() => setSignedIn(false)} />
      </header>

      <nav className="flex gap-1 border-b-2 border-black/80 bg-surface/70 px-4 pt-2">
        {VIEWS.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setView(name)}
            className={[
              "mc-button -mb-0.5 border-b-0 px-3 py-1.5 text-sm capitalize",
              view === name
                ? "bg-surface-raised text-slate-100"
                : "bg-surface-card/70 text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {name}
          </button>
        ))}
      </nav>

      <NeedsAttention />

      <main className="min-h-0 flex-1">
        {view === "board" && (isMobile ? <MobileBoard /> : <Board />)}
        {view === "table" && <TableView />}
        {view === "insights" && <Insights />}
      </main>

      <Drawer />
      <QuickAddSheet />

      {toast && (
        <div
          role="status"
          aria-live="polite"
          className={[
            "mc-panel fixed bottom-4 left-1/2 z-50 -translate-x-1/2 animate-fade-in px-4 py-2 text-sm shadow-lg",
            toast.tone === "error" ? "bg-stale-warn text-slate-900" : "text-slate-100",
          ].join(" ")}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
