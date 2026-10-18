"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { useState } from "react";
import { api, ApiError, errorMessage } from "@/lib/api";
import { toast } from "@/lib/toast";
import type { Recommendation } from "@/lib/types";
import { PriorityBadge } from "./ui";

/**
 * Human-in-the-loop action card (dashboard "Recommended actions" pattern):
 * linen card, 18px semibold action, 16px impact line, slate Approve, linen Dismiss,
 * sand Send to Telegram (heatmap AI-card button). Nothing changes until the seller approves.
 */
export default function RecommendationCard({
  rec,
  productName,
  onChange,
}: {
  rec: Recommendation;
  productName?: string | null;
  onChange?: () => void;
}) {
  const [status, setStatus] = useState(rec.status ?? "pending");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function act(kind: "approve" | "dismiss" | "send-telegram") {
    if (busy) return;
    setBusy(kind);
    setNote(null);
    try {
      const res = await api<{ status: string; sent_to_chats?: number }>(`/recommendations/${rec.id}/${kind}`, {
        method: "POST",
      });
      if (kind === "send-telegram") {
        const n = res.sent_to_chats ?? 0;
        setNote(n ? `Sent to ${n} Telegram chat${n === 1 ? "" : "s"}` : "No Telegram chat linked to this product yet");
        if (n) toast("Sent to Telegram");
      } else {
        setStatus(res.status);
        toast(res.status === "approved" ? "Recommendation approved" : "Recommendation dismissed");
        onChange?.();
      }
    } catch (e) {
      // 409 = someone already decided it (e.g. from Telegram): refresh instead of pretending.
      if (e instanceof ApiError && e.status === 409) {
        toast.info("This recommendation was already decided");
        onChange?.();
      } else {
        toast.error(errorMessage(e, "Couldn't update the recommendation"));
      }
    } finally {
      setBusy(null);
    }
  }

  const decided = status !== "pending";
  return (
    <div className={`card p-[26px] flex flex-col gap-5 transition-opacity ${decided ? "bg-linen border-dashed shadow-none" : ""}`}>
      <div className="flex flex-col gap-2 min-w-0">
        <div className="flex items-center gap-3 flex-wrap">
          <PriorityBadge priority={rec.priority} />
          {productName && (
            <Link href={`/products/${rec.product_id}`} className="text-[13px] font-semibold text-slate hover:underline underline-offset-2">
              {productName}
            </Link>
          )}
          {decided && <span className={`chip ml-auto ${status === "approved" ? "bg-sage" : "bg-linen"}`}>{status === "approved" ? "✓ Approved" : "Dismissed"}</span>}
        </div>
        <p className="font-semibold text-[18px] leading-[27px]">{rec.action_text}</p>
        <p className="text-[16px] leading-6 text-ink/80">{rec.impact_text}</p>
      </div>
      {!decided && (
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn btn-primary" disabled={!!busy} onClick={() => act("approve")}>
            {busy === "approve" ? "Approving…" : "Approve"}
          </button>
          <button className="btn btn-ghost" disabled={!!busy} onClick={() => act("dismiss")}>
            {busy === "dismiss" ? "Dismissing…" : "Dismiss"}
          </button>
          <button className="btn btn-sand px-[18px] text-[15px]" disabled={!!busy} onClick={() => act("send-telegram")}>
            <img src="/figma/heatmaps/imgContainer14.svg" alt="" width={16} height={13} />
            {busy === "send-telegram" ? "Sending…" : "Send to Telegram"}
          </button>
        </div>
      )}
      {note && (
        <p className="text-[14px] font-semibold border-t border-ink/20 pt-3" role="status">
          {note}
        </p>
      )}
    </div>
  );
}
