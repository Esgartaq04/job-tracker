import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { api } from "./client";
import type {
  Application,
  ApplicationDetail,
  AppStatus,
  Board,
  Funnel,
  IngestAccepted,
  SourceBreakdown,
  Tag,
  Velocity,
} from "./types";

export const queryKeys = {
  board: ["board"] as const,
  application: (id: string) => ["application", id] as const,
  tags: ["tags"] as const,
  funnel: ["stats", "funnel"] as const,
  velocity: ["stats", "velocity"] as const,
  sources: ["stats", "sources"] as const,
  search: (q: string) => ["search", q] as const,
};

export function useBoard(query?: string) {
  return useQuery({
    queryKey: [...queryKeys.board, query ?? ""],
    queryFn: () => api.get<Board>(`/applications/board${query ? `?q=${encodeURIComponent(query)}` : ""}`),
  });
}

export function useApplication(id: string | null) {
  return useQuery({
    queryKey: queryKeys.application(id ?? ""),
    queryFn: () => api.get<ApplicationDetail>(`/applications/${id}`),
    enabled: Boolean(id),
  });
}

export function useTags() {
  return useQuery({ queryKey: queryKeys.tags, queryFn: () => api.get<Tag[]>("/tags") });
}

export function useFunnel() {
  return useQuery({ queryKey: queryKeys.funnel, queryFn: () => api.get<Funnel>("/stats/funnel") });
}

export function useVelocity() {
  return useQuery({
    queryKey: queryKeys.velocity,
    queryFn: () => api.get<Velocity>("/stats/velocity?weeks=12"),
  });
}

export function useSources() {
  return useQuery({
    queryKey: queryKeys.sources,
    queryFn: () => api.get<SourceBreakdown[]>("/stats/sources"),
  });
}

/** Paste one or many URLs. The card appears before ingestion resolves. */
export function useIngest(): UseMutationResult<
  IngestAccepted[],
  Error,
  { urls: string[]; markAsApplied: boolean }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ urls, markAsApplied }) => {
      if (urls.length === 1) {
        const accepted = await api.post<IngestAccepted>("/ingest", {
          url: urls[0],
          mark_as_applied: markAsApplied,
        });
        return [accepted];
      }
      const batch = await api.post<{ accepted: IngestAccepted[] }>("/ingest/batch", {
        urls,
        mark_as_applied: markAsApplied,
      });
      return batch.accepted;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.board }),
  });
}

export function useCreateApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<ApplicationDetail>("/applications", payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.board }),
  });
}

export function useUpdateApplication(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.patch<ApplicationDetail>(`/applications/${id}`, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.application(id), updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.board });
    },
  });
}

export function useArchiveApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/applications/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.board }),
  });
}

export function useReingest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<ApplicationDetail>(`/applications/${id}/reingest`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.board }),
  });
}

export function useAddNote(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) =>
      api.post<ApplicationDetail>(`/applications/${id}/notes`, { text }),
    onSuccess: (updated) => queryClient.setQueryData(queryKeys.application(id), updated),
  });
}

export interface MoveVariables {
  id: string;
  toStatus: AppStatus;
  beforeId?: string | null;
  afterId?: string | null;
}

/**
 * Optimistic move: apply locally, fire the PATCH, roll back on failure
 * (README §6, "optimistic UI contract"). The server still owns the ranking —
 * we only send neighbour ids.
 */
export function useMoveApplication() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, toStatus, beforeId, afterId }: MoveVariables) =>
      api.patch<ApplicationDetail>(`/applications/${id}/move`, {
        to_status: toStatus,
        before_id: beforeId ?? null,
        after_id: afterId ?? null,
      }),

    onMutate: async ({ id, toStatus, beforeId }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.board });
      const snapshots = queryClient.getQueriesData<Board>({ queryKey: queryKeys.board });

      queryClient.setQueriesData<Board>({ queryKey: queryKeys.board }, (board) => {
        if (!board) return board;
        let moving: Application | undefined;
        const stripped = board.columns.map((column) => {
          const found = column.items.find((item) => item.id === id);
          if (found) moving = found;
          return {
            ...column,
            items: column.items.filter((item) => item.id !== id),
          };
        });
        if (!moving) return board;
        const moved: Application = { ...moving, status: toStatus };

        return {
          columns: stripped.map((column) => {
            if (column.status !== toStatus) {
              return { ...column, count: column.items.length };
            }
            const index = beforeId
              ? column.items.findIndex((item) => item.id === beforeId) + 1
              : 0;
            const items = [...column.items];
            items.splice(index < 0 ? items.length : index, 0, moved);
            return { ...column, items, count: items.length };
          }),
        };
      });

      return { snapshots };
    },

    onError: (_error, _variables, context) => {
      context?.snapshots.forEach(([key, data]) => queryClient.setQueryData(key, data));
    },

    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.board });
      queryClient.invalidateQueries({ queryKey: queryKeys.application(variables.id) });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
