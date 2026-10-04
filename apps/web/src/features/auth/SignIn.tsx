import { useEffect, useState } from "react";

import { api, setToken } from "../../api/client";
import { DimensionSwitcher } from "../theme/DimensionSwitcher";

const SPLASHES = [
  "Now with Sankey!",
  "Apply often!",
  "Ghosting is not a strategy!",
  "Follow up on Fridays!",
  "100% more blocks!",
  "Also try networking!",
  "Offer drops not guaranteed!",
  "Craft that cover letter!",
];

/**
 * Sign-in as a game title screen: logo, splash text and PRESS START. The form only
 * appears after START, so the first thing you see is the world you picked.
 */
export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [started, setStarted] = useState(false);
  const [splash] = useState(() => SPLASHES[Math.floor(Math.random() * SPLASHES.length)]);

  useEffect(() => {
    if (started) return;
    function onKeyDown(event: KeyboardEvent) {
      // A focused button already starts on Enter/Space; this covers focus elsewhere.
      if (event.target instanceof HTMLButtonElement) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setStarted(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [started]);

  return (
    <div className="mc-world flex h-full flex-col items-center justify-center p-6 text-slate-100">
      <div className="absolute right-4 top-4">
        <DimensionSwitcher showLabels={false} />
      </div>

      {started ? (
        <ProfileForm onSignedIn={onSignedIn} onBack={() => setStarted(false)} />
      ) : (
        <TitleScreen splash={splash} onStart={() => setStarted(true)} />
      )}

      <footer className="absolute inset-x-4 bottom-3 flex justify-between text-[11px] text-slate-400 mc-shadow">
        <span>Job Tracker 0.1</span>
        <span>Not an official Minecraft product</span>
      </footer>
    </div>
  );
}

function TitleScreen({ splash, onStart }: { splash: string; onStart: () => void }) {
  return (
    <div className="flex animate-fade-in flex-col items-center text-center">
      <div className="relative">
        <h1 className="font-[family-name:var(--font-pixel)] text-5xl font-bold uppercase leading-none tracking-wide text-slate-200 [text-shadow:4px_4px_0_rgb(0_0_0/0.55)] sm:text-7xl">
          Job
          <br />
          Tracker
        </h1>
        <p
          aria-hidden="true"
          className="absolute -bottom-2 -right-6 origin-center animate-splash whitespace-nowrap font-[family-name:var(--font-pixel)] text-sm font-bold text-[#ffff55] [text-shadow:2px_2px_0_#3f3f15] sm:-right-16 sm:text-base"
        >
          {splash}
        </p>
      </div>

      <button
        type="button"
        onClick={onStart}
        autoFocus
        className="mc-button mc-button-accent mt-14 flex min-w-64 items-center justify-center gap-3 px-8 py-3 font-[family-name:var(--font-pixel)] text-xl font-bold uppercase tracking-widest"
      >
        <span aria-hidden="true" className="animate-blink">
          ▶
        </span>
        Press Start
      </button>
      <p className="mt-3 text-xs text-slate-400 mc-shadow">or hit Enter</p>
    </div>
  );
}

function ProfileForm({ onSignedIn, onBack }: { onSignedIn: () => void; onBack: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await api.post<{ access_token: string }>(
        `/auth/${mode === "login" ? "login" : "register"}`,
        { email, password },
      );
      setToken(access_token);
      onSignedIn();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mc-panel w-full max-w-sm animate-fade-in p-6">
      <h1 className="mc-shadow text-center text-lg font-bold text-slate-100">
        {mode === "login" ? "Select Profile" : "Create New Profile"}
      </h1>
      <p className="mt-1 text-center text-sm text-slate-400">
        {mode === "login" ? "Sign in to your board." : "Create your board."}
      </p>

      <label className="mt-5 block text-xs uppercase tracking-wide text-slate-400">
        Email
        <input
          type="email"
          required
          autoFocus
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mc-slot mt-1 w-full px-3 py-2 text-sm normal-case tracking-normal text-slate-100 focus:border-accent-ink focus:outline-none"
        />
      </label>

      <label className="mt-3 block text-xs uppercase tracking-wide text-slate-400">
        Password
        <input
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mc-slot mt-1 w-full px-3 py-2 text-sm normal-case tracking-normal text-slate-100 focus:border-accent-ink focus:outline-none"
        />
      </label>

      {error && <p className="mt-3 text-sm text-stale-warn">{error}</p>}

      <button
        type="submit"
        disabled={busy}
        className="mc-button mc-button-accent mt-5 w-full py-2 text-sm font-bold disabled:opacity-50"
      >
        {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
      </button>

      <div className="mt-3 flex gap-2">
        <button type="button" onClick={onBack} className="mc-button px-3 py-1.5 text-xs">
          ◀ Back
        </button>
        <button
          type="button"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="mc-button flex-1 py-1.5 text-xs"
        >
          {mode === "login" ? "Need an account?" : "Already have an account?"}
        </button>
      </div>
    </form>
  );
}
