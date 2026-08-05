import { useState } from "react";

import { api, setToken } from "../../api/client";

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
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
    <div className="flex h-full items-center justify-center p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-xl border border-surface-border bg-surface-raised p-6"
      >
        <h1 className="text-lg font-medium text-slate-100">⬢ Tracker</h1>
        <p className="mt-1 text-sm text-slate-400">
          {mode === "login" ? "Sign in to your board." : "Create your board."}
        </p>

        <label className="mt-5 block text-xs uppercase tracking-wide text-slate-500">
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="mt-1 w-full rounded-md border border-surface-border bg-surface-card px-3 py-2 text-sm normal-case tracking-normal text-slate-100 focus:border-accent focus:outline-none"
          />
        </label>

        <label className="mt-3 block text-xs uppercase tracking-wide text-slate-500">
          Password
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full rounded-md border border-surface-border bg-surface-card px-3 py-2 text-sm normal-case tracking-normal text-slate-100 focus:border-accent focus:outline-none"
          />
        </label>

        {error && <p className="mt-3 text-sm text-stale-warn">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="mt-5 w-full rounded-md bg-accent py-2 text-sm font-medium text-white transition hover:bg-accent-muted disabled:opacity-50"
        >
          {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
        </button>

        <button
          type="button"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="mt-3 w-full text-center text-xs text-slate-400 hover:text-slate-200"
        >
          {mode === "login" ? "Need an account?" : "Already have an account?"}
        </button>
      </form>
    </div>
  );
}
