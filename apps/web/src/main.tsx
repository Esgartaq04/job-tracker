import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
// `/react`, not `/next` — this is a Vite SPA, and the `/next` entry point imports
// `next/navigation`, which isn't a dependency here.
import { Analytics } from "@vercel/analytics/react";

import { App } from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // SSE pushes the interesting changes, so polling would be redundant.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
});

// Registered after load so it never competes with the first render. Dev keeps the
// worker off: a cached shell during HMR is a debugging trap.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.info("service worker registration skipped:", error.message);
    });
  });
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      {/* Mounted here rather than inside App so it survives the signed-out branch.
          Inert off Vercel: the script only loads on a Vercel deployment. */}
      <Analytics />
    </QueryClientProvider>
  </React.StrictMode>,
);
