// Same-origin in dev (the Vite proxy) and in Docker (nginx), so this is empty in both.
// Set VITE_API_ORIGIN when the SPA is served from a different host than the API — e.g.
// Vercel in front of Render. Vite inlines it at build time: changing it in a dashboard
// does nothing until the next deploy.
const API_ORIGIN = (import.meta.env.VITE_API_ORIGIN ?? "").replace(/\/$/, "");
const API_BASE = `${API_ORIGIN}/api/v1`;
const TOKEN_KEY = "job-tracker.token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  if (response.status === 401) {
    setToken(null);
    window.dispatchEvent(new CustomEvent("job-tracker:signed-out"));
    throw new ApiError(401, "Session expired — sign in again");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => undefined);
    const detail = (body as { detail?: unknown } | undefined)?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof (detail as { message?: string })?.message === "string"
          ? (detail as { message: string }).message
          : `Request failed (${response.status})`;
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export { API_BASE };
