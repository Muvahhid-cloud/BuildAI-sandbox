// Live check of an operation being prepared in a form (an opening's size, a wall to remove, a
// room's new type): debounced, latest wins, stale answers dropped. The answer is also published
// as the session's draft, so the plan shows the model the server would build for it.
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/errors";
import type { EditOperation, EditPreview } from "@/lib/api/schemas";

import { useEditStore } from "./store";

export const DRAFT_CHECK_DELAY_MS = 250;

export interface DraftCheck {
  /** The server's answer for `op` (null while checking or without an op). */
  preview: EditPreview | null;
  checking: boolean;
  /** The check itself failed (network, server). */
  error: string | null;
}

export function useDraftCheck(op: EditOperation | null): DraftCheck {
  const cursor = useEditStore((s) => s.cursor);
  const key = op ? `${cursor}:${JSON.stringify(op)}` : null;
  const [result, setResult] = useState<{
    key: string;
    preview: EditPreview | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!key || !op) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      useEditStore
        .getState()
        .check(op, controller.signal)
        .then((preview) => {
          setResult({ key, preview, error: null });
          useEditStore.getState().setDraft({ key, op, preview });
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setResult({
            key,
            preview: null,
            error: err instanceof ApiError ? err.message : "The change could not be checked.",
          });
        });
    }, DRAFT_CHECK_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
      // The plan stops showing this draft once the form moves on or closes.
      const store = useEditStore.getState();
      if (store.draft?.key === key) store.setDraft(null);
    };
    // `op` is described by `key`; re-check only when it changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = result && result.key === key ? result : null;
  return {
    preview: current?.preview ?? null,
    checking: key !== null && current === null,
    error: current?.error ?? null,
  };
}
