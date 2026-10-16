"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamUrl } from "./api";

export interface RunProgress {
  runId: string;
  done: number;
  failed: number;
  total: number;
  finished: boolean;
}

/** Starts a check run and follows its SSE stream; calls onResult per finished job. */
export function useRun(productId: string | null, onUpdate?: () => void) {
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const source = useRef<EventSource | null>(null);
  const updateRef = useRef(onUpdate);
  updateRef.current = onUpdate;

  useEffect(() => () => source.current?.close(), []);

  const start = useCallback(
    async (body?: { pincodes?: string[]; platforms?: string[] }) => {
      if (!productId) return;
      setError(null);
      try {
        const { run_id, estimated_credits } = await api<{ run_id: string; estimated_credits: number }>(
          `/products/${productId}/runs`,
          { method: "POST", json: body ?? {} },
        );
        setProgress({ runId: run_id, done: 0, failed: 0, total: estimated_credits, finished: false });
        source.current?.close();
        const es = new EventSource(streamUrl(run_id));
        source.current = es;
        let refreshTimer: ReturnType<typeof setTimeout> | null = null;
        const refreshSoon = () => {
          if (refreshTimer) return;
          refreshTimer = setTimeout(() => {
            refreshTimer = null;
            updateRef.current?.();
          }, 700);
        };
        es.addEventListener("result", () => {
          setProgress((p) => p && { ...p, done: p.done + 1 });
          refreshSoon();
        });
        es.addEventListener("job_failed", () => setProgress((p) => p && { ...p, failed: p.failed + 1 }));
        es.addEventListener("run_done", (ev) => {
          try {
            const data = JSON.parse((ev as MessageEvent).data);
            setProgress((p) =>
              p && {
                ...p,
                done: data.done_jobs ?? p.done,
                failed: data.failed_jobs ?? p.failed,
                total: data.total_jobs ?? p.total,
                finished: true,
              },
            );
          } catch {
            setProgress((p) => p && { ...p, finished: true });
          }
          es.close();
          // The backend regenerates summaries and recommendations right after the run.
          setTimeout(() => updateRef.current?.(), 1200);
        });
        es.onerror = () => {
          if (es.readyState === EventSource.CLOSED) setProgress((p) => p && { ...p, finished: true });
        };
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not start check");
      }
    },
    [productId],
  );

  return { start, progress, error, running: !!progress && !progress.finished };
}
