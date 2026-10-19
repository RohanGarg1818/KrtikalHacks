"use client";

import { useMemo, useState } from "react";
import { platformLabel } from "@/lib/format";
import type { AgentJobState } from "@/lib/useRun";

/** The live browser of a running TinyFish agent (its streaming URL in an iframe). */
export default function LiveBrowser({ jobs }: { jobs: AgentJobState[] }) {
  const streams = useMemo(
    () =>
      jobs
        .filter((j) => j.phase === "running")
        .map((j) => ({ job: j, url: [...j.steps].reverse().find((s) => s.kind === "stream" && s.detail?.startsWith("https://"))?.detail }))
        .filter((s): s is { job: AgentJobState; url: string } => Boolean(s.url)),
    [jobs],
  );
  const [picked, setPicked] = useState<string | null>(null);
  if (!streams.length) return null;
  const active = streams.find((s) => s.job.key === picked) ?? streams[0];
  const label = (j: AgentJobState) => `${platformLabel(j.job.platform)} · ${j.job.pincode}`;

  return (
    <section className="p-4 sm:p-[22px] bg-ink text-linen border-b-2 border-ink" aria-label="Live agent browser">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <p className="font-semibold text-[15px] flex items-center gap-2">
          <span className="inline-block size-2.5 rounded-full bg-[#e5484d] animate-pulse" aria-hidden />
          Watching the TinyFish agent live: {label(active.job)}
        </p>
        {streams.length > 1 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Choose which agent to watch">
            {streams.map((s) => (
              <button
                key={s.job.key}
                type="button"
                onClick={() => setPicked(s.job.key)}
                aria-pressed={s.job.key === active.job.key}
                className={`rounded-full border-2 border-linen px-3 py-1 text-[12px] font-semibold ${s.job.key === active.job.key ? "bg-linen text-ink" : "text-linen"}`}
              >
                {label(s.job)}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="relative w-full overflow-hidden rounded-[12px] border-2 border-linen" style={{ paddingBottom: "56.25%" }}>
        <iframe
          key={active.url}
          src={active.url}
          title={`Live TinyFish browser: ${label(active.job)}`}
          className="absolute inset-0 h-full w-full bg-white"
          allow="fullscreen"
        />
      </div>
      <p className="mt-2 text-[12px] text-linen/70">The view ends when the agent finishes; its result and proof screenshot then appear below.</p>
    </section>
  );
}
