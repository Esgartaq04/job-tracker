import { ApiError } from "../../api/client";
import type { AiKeyState } from "../../api/types";

/** The server's "no key" (428) and "Claude rejected the key" (424): both fixed by the key dialog. */
export function isAiKeyError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 428 || error.status === 424);
}

/**
 * Whether an AI feature is worth trying. While the key state is loading, or couldn't be
 * fetched, it is: the server answers 428/424 if there is really no usable key, and that
 * is handled where the call is made.
 */
export function aiUsable(state: AiKeyState | undefined): boolean {
  return state === undefined || (state.has_key && state.status !== "rejected");
}
