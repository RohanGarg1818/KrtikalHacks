"use client";

import type { ReactNode } from "react";
import CountUp from "./motion/CountUp";

/** Status is never colour alone: each one carries an icon and a label. */
export const STATUS_META: Record<string, { label: string; icon: string; cls: string }> = {
  in_stock: { label: "In stock", icon: "✓", cls: "bg-sage text-linen" },
  out_of_stock: { label: "Out of stock", icon: "✕", cls: "bg-linen border-dashed" },
  price_gap: { label: "Price gap", icon: "₹", cls: "bg-sand" },
  stale: { label: "Not checked recently", icon: "…", cls: "bg-linen opacity-50" },
  not_tracked: { label: "Not tracked", icon: "–", cls: "bg-linen opacity-50" },
  failed: { label: "Check failed", icon: "!", cls: "bg-linen opacity-50" },
};

/** 24px round status dot from the design (sage + check uses the Figma asset). */
export function StatusDot({ status, size = 24 }: { status: string; size?: number }) {
  const m = STATUS_META[status] ?? STATUS_META.stale;
  if (status === "in_stock")
    // eslint-disable-next-line @next/next/no-img-element
    return <img src="/figma/shell/pin-in-stock.svg" alt={m.label} title={m.label} width={size} height={size} className="shrink-0" />;
  return (
    <span
      title={m.label}
      aria-label={m.label}
      className={`grid place-items-center shrink-0 rounded-full border-2 border-ink text-ink font-bold ${m.cls}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.46) }}
    >
      {m.icon}
    </span>
  );
}

export function PincodeStrip({ strip, size = 24 }: { strip: { pincode: string; status: string; platform: string }[]; size?: number }) {
  if (!strip.length) return <p className="text-sm text-ink/70">No checks yet</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {strip.map((s) => (
        <StatusDot key={`${s.platform}-${s.pincode}`} status={s.status} size={size} />
      ))}
    </div>
  );
}

export function StatusBadge({ status, compact }: { status: string; compact?: boolean }) {
  const m = STATUS_META[status] ?? STATUS_META.stale;
  return (
    <span className={`chip ${m.cls}`} title={m.label}>
      <span aria-hidden>{m.icon}</span>
      {!compact && m.label}
    </span>
  );
}

const PRIORITY_META: Record<string, { cls: string; label: string }> = {
  high: { cls: "bg-ink text-linen", label: "High" },
  medium: { cls: "bg-sand", label: "Medium" },
  low: { cls: "bg-linen", label: "Low" },
};

export function PriorityBadge({ priority }: { priority: string }) {
  const m = PRIORITY_META[priority] ?? PRIORITY_META.low;
  return <span className={`chip ${m.cls}`}>{m.label}</span>;
}

export function Sticker({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`sticker ${className}`}>{children}</span>;
}

/**
 * Big coloured stat tile: eyebrow, 80px Fraunces number, caption.
 * Pass `count` (+ optional `format`, `suffix`) instead of `value` to count the number up.
 */
export function StatTile({
  eyebrow,
  value,
  count,
  format,
  suffix,
  caption,
  tone = "linen",
  height = 200,
  children,
}: {
  eyebrow: string;
  value?: ReactNode;
  count?: number;
  format?: (n: number) => string;
  suffix?: ReactNode;
  caption?: ReactNode;
  tone?: "ink" | "sand" | "sage" | "slate" | "linen";
  height?: number;
  children?: ReactNode;
}) {
  const bg = { ink: "bg-ink text-linen", sand: "bg-sand text-ink", sage: "bg-sage text-ink", slate: "bg-slate text-linen", linen: "bg-linen text-ink" }[tone];
  return (
    <div className={`card ${bg} flex flex-col justify-between p-[26px] min-w-0`} style={{ minHeight: height }}>
      <p className="eyebrow">{eyebrow}</p>
      {(count != null || value != null) && (
        <p className="font-display text-[80px] leading-[80px] tracking-[-1.6px] -mt-1">
          {count != null ? (
            <>
              <CountUp value={count} format={format} />
              {suffix}
            </>
          ) : (
            value
          )}
        </p>
      )}
      {caption != null && <p className="text-[15px] leading-[22.5px] font-semibold">{caption}</p>}
      {children}
    </div>
  );
}

export function Skeleton({ className = "h-6 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="card p-6 space-y-3">
      <Skeleton className="h-5 w-1/3" />
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-4 w-full" />
      ))}
    </div>
  );
}

export function ErrorCard({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div className="card p-6 bg-sand">
      <p className="font-semibold text-lg">Couldn&apos;t load this.</p>
      <p className="text-[15px] mt-1">
        {message}. Is the backend running on <code>localhost:8000</code>?
      </p>
      {onRetry && (
        <button className="btn btn-ghost btn-sm mt-4" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="border-2 border-dashed border-ink/40 rounded-[20px] p-8 text-center">
      <p className="font-display text-2xl">{title}</p>
      {children && <div className="text-[15px] mt-2 text-ink/80">{children}</div>}
    </div>
  );
}

/** Section heading (Fraunces 32) with the design's 2px divider. */
export function SectionTitle({ children, action, size = 32 }: { children: ReactNode; action?: ReactNode; size?: number }) {
  return (
    <div className="section-head mb-6">
      <h2 style={{ fontSize: size, lineHeight: 1.25, letterSpacing: -size * 0.02 }}>{children}</h2>
      {action}
    </div>
  );
}

export function Sparkline({
  values,
  width = 120,
  height = 36,
  stroke = "var(--ink)",
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  stroke?: string;
}) {
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return <svg width={width} height={height} />;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const pts = values
    .map((v, i) => (v == null ? null : `${i * step},${height - 4 - ((v - min) / span) * (height - 8)}`))
    .filter(Boolean)
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={pts} fill="none" stroke={stroke} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Usage bar. `dark` = linen text on ink (plan tile); default = ink on linen. */
export function Meter({ value, max, label, dark }: { value: number; max: number | null; label: string; dark?: boolean }) {
  const ratio = max ? Math.min(1, value / max) : 0.8;
  return (
    <div className="flex flex-col gap-1">
      <div className={`flex justify-between text-[14px] leading-[21px] font-medium ${dark ? "text-linen" : "text-ink"}`}>
        <span>
          {label}
          {" "}
          <CountUp value={value} />
          {max ? `/${max}` : ""}
        </span>
      </div>
      {/* Fill slides in with a transform; the rounded track clips it, so it looks like a width bar. */}
      <div className={`h-[10px] rounded-full overflow-hidden ${dark ? "bg-linen/20" : "bg-ink/15"}`}>
        <div
          className="h-full bg-sand rounded-full transition-transform duration-500"
          style={{ transform: `translateX(${(ratio - 1) * 100}%)` }}
        />
      </div>
    </div>
  );
}

/** Design toggle: slate track + linen knob when on, linen track when off. */
export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="inline-flex items-center gap-3 cursor-pointer select-none text-[15px] font-semibold">
      {label}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative shrink-0 w-[52px] h-[28px] rounded-full border-2 border-ink transition-colors ${checked ? "bg-slate" : "bg-linen"}`}
      >
        <span
          className={`absolute top-[2px] left-[2px] size-[20px] rounded-full border-2 border-ink transition-[transform,background-color] ${checked ? "translate-x-[24px] bg-linen" : "bg-ink"}`}
        />
      </button>
    </label>
  );
}
