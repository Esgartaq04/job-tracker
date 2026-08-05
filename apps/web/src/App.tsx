import { useEffect, useState } from "react";

import { getToken } from "./api/client";
import { useServerEvents } from "./api/events";
import { AccountMenu } from "./features/auth/AccountMenu";
import { SignIn } from "./features/auth/SignIn";
import { Board } from "./features/board/Board";
import { Drawer } from "./features/detail/Drawer";
import { Insights } from "./features/insights/Insights";
import { QuickAdd } from "./features/quickadd/QuickAdd";
import { TableView } from "./features/table/TableView";
import { TimelineView } from "./features/timeline/TimelineView";
import { useUi, type ViewName } from "./lib/store";

const VIEWS: ViewName[] = ["board", "table", "timeline", "insights"];

export function App() {
  const [signedIn, setSignedIn] = useState(() => Boolean(getToken()));
  const view = useUi((state) => state.view);
  const setView = useUi((state) => state.setView);
  const query = useUi((state) => state.query);
  const setQuery = useUi((state) => state.setQuery);
  const toast = useUi((state) => state.toast);
  const dismissToast = useUi((state) => state.dismissToast);

  useServerEvents(signedIn);

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
    <div className="flex h-full flex-col bg-surface text-slate-100">
      <header className="flex items-center gap-3 border-b border-surface-border px-4 py-2.5">
        <span className="hidden text-sm font-semibold text-slate-200 sm:inline">⬢ Tracker</span>
        <QuickAdd />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search…"
          aria-label="Search applications"
          className="hidden w-40 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none md:block"
        />
        <AccountMenu onSignOut={() => setSignedIn(false)} />
      </header>

      <nav className="flex gap-1 border-b border-surface-border px-4">
        {VIEWS.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setView(name)}
            className={[
              "px-3 py-2 text-sm capitalize transition",
              view === name
                ? "border-b-2 border-accent text-slate-100"
                : "text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {name}
          </button>
        ))}
      </nav>

      <main className="min-h-0 flex-1">
        {view === "board" && <Board />}
        {view === "table" && <TableView />}
        {view === "timeline" && <TimelineView />}
        {view === "insights" && <Insights />}
      </main>

      <Drawer />

      {toast && (
        <div
          role="status"
          aria-live="polite"
          className={[
            "fixed bottom-4 left-1/2 z-50 -translate-x-1/2 animate-fade-in rounded-md px-4 py-2 text-sm shadow-lg",
            toast.tone === "error"
              ? "bg-stale-warn/90 text-slate-900"
              : "bg-surface-card text-slate-100 ring-1 ring-surface-border",
          ].join(" ")}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}
