import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { API_BASE, getToken } from "./client";
import { queryKeys } from "./hooks";

type ServerEvent = {
  type: string;
  at: string;
  data: { application_id?: string; ingest_status?: string; error?: string | null };
};

/**
 * Subscribes to ingest progress so a pasted card fills itself in without a refetch
 * loop (README §7.2). `EventSource` can't set headers, so the token rides along as a
 * query parameter — same trade-off the API's dependency documents.
 */
export function useServerEvents(enabled: boolean): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;
    const token = getToken();
    if (!token) return;

    const source = new EventSource(
      `${API_BASE}/events?access_token=${encodeURIComponent(token)}`,
    );

    const refresh = (event: MessageEvent<string>) => {
      let payload: ServerEvent | undefined;
      try {
        payload = JSON.parse(event.data) as ServerEvent;
      } catch {
        return;
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.board });
      queryClient.invalidateQueries({ queryKey: queryKeys.reminders });
      const id = payload?.data?.application_id;
      if (id) queryClient.invalidateQueries({ queryKey: queryKeys.application(id) });
    };

    for (const name of [
      "ingest.started",
      "ingest.completed",
      "ingest.failed",
      "application.created",
      "application.updated",
      "application.moved",
      "application.archived",
      "reminder.due",
    ]) {
      source.addEventListener(name, refresh as EventListener);
    }

    // The browser reconnects on its own; log once rather than thrashing state.
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        console.info("event stream closed; the browser will retry");
      }
    };

    return () => source.close();
  }, [enabled, queryClient]);
}
