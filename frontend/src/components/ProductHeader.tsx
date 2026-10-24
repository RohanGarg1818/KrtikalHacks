"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import type { ReactNode } from "react";
import { useApi } from "@/lib/api";
import type { CheckQuota, Product } from "@/lib/types";
import { Skeleton } from "./ui";

const TABS = [
  { key: "overview", label: "Overview", href: (id: string) => `/products/${id}` },
  { key: "heatmap", label: "Heatmap", href: (id: string) => `/heatmap?product=${id}` },
  { key: "telegram", label: "Telegram", href: (id: string) => `/products/${id}/telegram` },
  { key: "settings", label: "Settings", href: (id: string) => `/products/${id}/settings` },
];

/**
 * Product page header from the Figma heatmap frame: Fraunces 48px title,
 * section tabs (active = slate text + 3px slate underline), and an action slot
 * (the slate "Re-check now" button by default).
 */
export default function ProductHeader({
  productId,
  active,
  action,
  title,
}: {
  productId: string;
  active: "overview" | "heatmap" | "telegram" | "settings";
  action?: ReactNode;
  title?: ReactNode;
}) {
  const { data: product } = useApi<Product>(`/products/${productId}`);
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 pb-6">
      {/* Below ~20rem of spare width the action drops under the title instead of squeezing it. */}
      <div className="min-w-[min(100%,20rem)] flex-1">
        {(title ?? product?.name) ? (
          <h1 className="text-[36px] md:text-[48px] leading-[1.1] tracking-[-1.2px] break-words">{title ?? product?.name}</h1>
        ) : (
          <Skeleton className="h-10 md:h-[53px] w-full max-w-96" />
        )}
        <nav className="flex gap-5 sm:gap-8 items-center pt-2 overflow-x-auto" aria-label="Product sections">
          {TABS.map((t) => {
            const on = t.key === active;
            return (
              <Link
                key={t.key}
                href={t.href(productId)}
                aria-current={on ? "page" : undefined}
                className={`text-[16px] leading-6 shrink-0 ${on ? "font-semibold text-slate border-b-[3px] border-slate pt-2 pb-[5px]" : "font-medium text-ink py-2 hover:text-slate transition-colors"}`}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {action}
    </div>
  );
}

export function RecheckButton({
  onClick,
  running,
  label,
  disabled,
  productId,
}: {
  onClick: () => void;
  running?: boolean;
  label?: string;
  disabled?: boolean;
  /** When given, the button shows "Out of check now" once the month's manual checks are used. */
  productId?: string;
}) {
  const { out, title } = useCheckQuota(productId);
  const outNow = out && !running;
  return (
    <button data-mochi="recheck" className="btn btn-primary h-12 px-[26px] text-[15px]" onClick={onClick} disabled={running || disabled || outNow} title={title}>
      <img src="/figma/shell/refresh.svg" alt="" width={13} height={13} className={running ? "animate-spin" : ""} />
      {outNow ? "Out of check now" : (label ?? (running ? "Checking…" : "Re-check now"))}
    </button>
  );
}

/** Manual re-checks left this month for a product, plus the "Out of check now" button state. */
export function useCheckQuota(productId: string | null | undefined) {
  const quota = useApi<CheckQuota>(productId ? `/products/${productId}/check-quota` : null);
  const out = quota.data ? quota.data.left <= 0 : false;
  const title = quota.data
    ? out
      ? `All ${quota.data.limit} manual checks used this month. Resets ${new Date(quota.data.resets_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}; automatic checks still run ${quota.data.scheduled_per_day}× a day.`
      : `${quota.data.left} of ${quota.data.limit} manual checks left this month`
    : undefined;
  return { quota: quota.data, out, title };
}
