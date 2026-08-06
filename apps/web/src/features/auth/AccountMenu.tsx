import { useEffect, useRef, useState } from "react";

import { getToken, setToken } from "../../api/client";
import { useUi } from "../../lib/store";
import { enableDesktopNotifications } from "../reminders/NeedsAttention";

/**
 * Account menu. Its reason to exist beyond sign-out is the extension token: the
 * browser extension posts to the API with the same bearer token this app holds, and
 * pasting it into the extension's settings is how the two get connected.
 */
export function AccountMenu({ onSignOut }: { onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const notify = useUi((state) => state.notify);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function copyToken() {
    const token = getToken();
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
      notify("Token copied — paste it into the extension");
    } catch {
      // Clipboard access needs a secure context; show it so the user can copy by hand.
      window.prompt("Copy this into the extension's settings:", token);
    }
    setOpen(false);
  }

  return (
    <div ref={container} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account"
        className="rounded-md px-2 py-2 text-sm text-slate-400 transition hover:text-slate-100"
      >
        👤
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1 w-56 animate-fade-in rounded-md border border-surface-border bg-surface-card py-1 shadow-xl"
        >
          <button
            type="button"
            role="menuitem"
            onClick={copyToken}
            className="block w-full px-3 py-2 text-left text-sm text-slate-200 hover:bg-surface-border/60"
          >
            Copy extension token
            <span className="block text-[11px] text-slate-500">
              Connects the browser extension
            </span>
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              const permission = await enableDesktopNotifications();
              notify(
                permission === "granted"
                  ? "Notifications on — you'll hear about overdue follow-ups"
                  : "Notifications are blocked in your browser settings",
                permission === "granted" ? "info" : "error",
              );
              setOpen(false);
            }}
            className="block w-full px-3 py-2 text-left text-sm text-slate-200 hover:bg-surface-border/60"
          >
            Enable notifications
            <span className="block text-[11px] text-slate-500">
              A daily nudge about overdue follow-ups
            </span>
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setToken(null);
              onSignOut();
            }}
            className="block w-full px-3 py-2 text-left text-sm text-slate-200 hover:bg-surface-border/60"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
