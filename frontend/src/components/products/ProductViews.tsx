"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import type { ProductCard } from "@/lib/types";
import { mediaUrl } from "@/lib/api";
import { platformLabel, timeAgo } from "@/lib/format";

const A = "/figma/product";

export type ProductState = "attention" | "healthy" | "paused";

/** Same rules as the backend `filter` param (GET /products). */
export function productState(p: ProductCard): ProductState {
  if (p.paused) return "paused";
  return p.status_strip.some((s) => s.status !== "in_stock") ? "attention" : "healthy";
}

export function coverage(p: ProductCard) {
  const total = p.status_strip.length;
  const ok = p.status_strip.filter((s) => s.status === "in_stock" || s.status === "price_gap").length;
  return { ok, total, ratio: total ? ok / total : 0 };
}

export function platformsOf(p: ProductCard) {
  return [...new Set(p.status_strip.map((s) => s.platform))];
}

/** API gives a percent vs the average rival price. */
export function priceVsRivals(v: number | null | undefined) {
  if (v == null) return "—";
  if (Math.abs(v) < 0.5) return "Matched";
  return `${Math.abs(v).toFixed(1)}% ${v < 0 ? "below" : "above"}`;
}

/* Product tile icons from the Figma frame, matched by product keyword.
   Unknown products get their own photo (if any) or a neutral box icon. */
const ICONS: { re: RegExp; src: string; w: number; h: number }[] = [
  { re: /milk|curd|dahi|lassi|paneer|butter|ghee|juice|water|aamras|drink/i, src: "imgContainer4", w: 16, h: 20 },
  { re: /bread|bun|pav|cake/i, src: "imgContainer6", w: 22, h: 14 },
  { re: /atta|flour|maida|rice|dal|besan|grain/i, src: "imgContainer8", w: 16, h: 16 },
  { re: /salt|sugar|masala powder|spice/i, src: "imgContainer9", w: 16, h: 20 },
  { re: /noodle|maggi|pasta|soup/i, src: "imgContainer10", w: 20, h: 20 },
  { re: /biscuit|cookie|parle|rusk|bhujia|namkeen|chips|snack/i, src: "imgContainer11", w: 20, h: 20.025 },
  { re: /\boil\b|sunflower|mustard/i, src: "imgContainer12", w: 18, h: 18 },
  { re: /detergent|surf|soap|wash|cleaner|shampoo/i, src: "imgContainer13", w: 16, h: 20 },
];

const TILE_BG: Record<ProductState, string> = { attention: "bg-sand", healthy: "bg-sage", paused: "bg-linen" };

export function ProductIcon({ p }: { p: ProductCard }) {
  const state = productState(p);
  const match = ICONS.find((i) => i.re.test(`${p.name} ${p.search_query}`));
  const photo = !match ? mediaUrl(p.image_url) : null;
  return (
    <span className={`grid place-items-center shrink-0 size-12 rounded-[12px] border-2 border-ink overflow-hidden ${TILE_BG[state]}`}>
      {match ? (
        <img src={`${A}/${match.src}.svg`} alt="" width={match.w} height={match.h} />
      ) : photo ? (
        <img src={photo} alt="" className="size-full object-cover" />
      ) : (
        <img src="/figma/shell/nav-products.svg" alt="" width={18} height={18} className="brightness-0" />
      )}
    </span>
  );
}

export function StatusPill({ state }: { state: ProductState }) {
  const base = "inline-flex items-center gap-[6px] px-[14px] py-[6px] rounded-full border-2 border-ink text-[14px] leading-[21px] font-semibold whitespace-nowrap";
  if (state === "attention")
    return (
      <span className={`${base} bg-sand`}>
        <img src={`${A}/imgContainer5.svg`} alt="" width={14.667} height={12.667} className="shrink-0" />
        Needs attention
      </span>
    );
  if (state === "healthy")
    return (
      <span className={`${base} bg-sage`}>
        <img src={`${A}/imgContainer7.svg`} alt="" width={13.333} height={13.333} className="shrink-0" />
        Healthy
      </span>
    );
  return (
    <span className={`${base} bg-linen`}>
      <span aria-hidden className="text-[12px] leading-none">‖</span>
      Paused
    </span>
  );
}

const DOT_ORDER: Record<string, number> = { in_stock: 0, out_of_stock: 1, price_gap: 2 };

function Dot({ status }: { status: string }) {
  if (status === "in_stock") return <img src={`${A}/imgBackgroundBorder.svg`} alt="In stock" title="In stock" width={16} height={19} className="shrink-0" />;
  if (status === "out_of_stock")
    return <span title="Out of stock" aria-label="Out of stock" className="shrink-0 size-4 rounded-full border-2 border-dashed border-ink bg-linen" />;
  if (status === "price_gap")
    return (
      <span title="Price gap" aria-label="Price gap" className="shrink-0 grid place-items-center w-4 h-[19px] rounded-full border-2 border-ink bg-sand text-[10px] leading-[15px] font-bold">
        ₹
      </span>
    );
  return <span title="Not checked recently" aria-label="Not checked recently" className="shrink-0 size-4 rounded-full border-2 border-ink bg-linen opacity-50" />;
}

/** Compact 6-dot strip: problems are always kept, in-stock dots fill the rest; "+N" when truncated. */
export function MiniStrip({ strip, max = 6 }: { strip: ProductCard["status_strip"]; max?: number }) {
  if (!strip.length) return <p className="text-[13px] text-ink/70">No checks yet</p>;
  const problems = strip.filter((s) => s.status !== "in_stock");
  const ok = strip.filter((s) => s.status === "in_stock");
  const picked = [...problems.slice(0, max), ...ok.slice(0, Math.max(0, max - problems.length))].sort(
    (a, b) => (DOT_ORDER[a.status] ?? 3) - (DOT_ORDER[b.status] ?? 3),
  );
  const extra = strip.length - picked.length;
  return (
    <div className="flex items-center gap-[6px] h-4">
      {picked.map((s) => (
        <Dot key={`${s.platform}-${s.pincode}`} status={s.status} />
      ))}
      {extra > 0 && <span className="text-[12px] font-semibold text-ink/70">+{extra}</span>}
    </div>
  );
}

function Telegram({ p }: { p: ProductCard }) {
  return (
    <Link href={`/products/${p.id}/telegram`} className="inline-flex items-center gap-[6px] hover:underline underline-offset-4">
      {p.telegram_connected ? (
        <>
          <span className="shrink-0 size-[10px] rounded-full bg-sage border border-ink" />
          <span className="text-[15px] leading-[22.5px] font-medium">Connected</span>
        </>
      ) : (
        <>
          <span className="shrink-0 size-[10px] rounded-full bg-ink/30 border border-ink" />
          <span className="text-[15px] leading-[22.5px] text-ink/60">Not connected</span>
        </>
      )}
    </Link>
  );
}

const TH = "text-left text-[14px] leading-[21px] font-bold tracking-[0.7px] uppercase px-3 py-[18px] align-bottom";
const TD = "px-3 py-[18px] align-middle";

export function ProductTable({ rows }: { rows: ProductCard[] }) {
  return (
    <div className="bg-linen border-2 border-ink rounded-[20px] shadow-[6px_6px_0_var(--ink)] overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px]">
          <thead className="bg-sand border-b-2 border-ink">
            <tr>
              <th className={`${TH} pl-6`}>Product</th>
              <th className={TH}>Stock</th>
              <th className={TH}>Price vs rivals</th>
              <th className={TH}>Status</th>
              <th className={TH}>Last checked</th>
              <th className={`${TH} pr-6`}>Telegram</th>
            </tr>
          </thead>
          <tbody className="stagger">
            {rows.map((p) => {
              const c = coverage(p);
              const platforms = platformsOf(p).map(platformLabel).join(" · ");
              return (
                <tr key={p.id} className="border-t border-ink/20 first:border-t-0 hover:bg-sand/15 transition-colors">
                  <td className={`${TD} pl-6`}>
                    <Link href={`/products/${p.id}`} className="flex items-center gap-[14px] group">
                      <ProductIcon p={p} />
                      <span className="min-w-[150px]">
                        <span className="block text-[17px] leading-[21.25px] font-semibold group-hover:underline underline-offset-4">{p.name}</span>
                        <span className="block text-[15px] leading-[22.5px] text-ink/80">{platforms || "No platforms yet"}</span>
                      </span>
                    </Link>
                  </td>
                  <td className={TD}>
                    <div className="flex flex-col gap-[6px]">
                      <span className="text-[15px] leading-[22.5px] font-semibold whitespace-nowrap">
                        {c.ok} of {c.total} pincodes
                      </span>
                      <MiniStrip strip={p.status_strip} />
                    </div>
                  </td>
                  <td className={`${TD} text-[16px] leading-6 font-semibold whitespace-nowrap`}>{priceVsRivals(p.price_position_vs_avg_rival)}</td>
                  <td className={TD}>
                    <StatusPill state={productState(p)} />
                  </td>
                  <td className={`${TD} text-[15px] leading-[22.5px] whitespace-nowrap`}>{timeAgo(p.last_checked)}</td>
                  <td className={`${TD} pr-6`}>
                    <Telegram p={p} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Grid / mobile card, same composition as the dashboard product cards. */
export function ProductGridCard({ p }: { p: ProductCard }) {
  const c = coverage(p);
  const platforms = platformsOf(p).map(platformLabel).join(" · ");
  return (
    <div className="card card-lift flex flex-col gap-4 p-6 min-w-0">
      <Link href={`/products/${p.id}`} className="flex items-start gap-[14px] group">
        <ProductIcon p={p} />
        <span className="min-w-0 flex-1">
          <span className="block text-[18px] leading-[24px] font-semibold group-hover:underline underline-offset-4">{p.name}</span>
          <span className="block text-[15px] leading-[22.5px] text-ink/80">{platforms || "No platforms yet"}</span>
        </span>
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-[6px]">
          <span className="text-[15px] leading-[22.5px] font-semibold">
            {c.ok} of {c.total} pincodes
          </span>
          <MiniStrip strip={p.status_strip} />
        </div>
        <StatusPill state={productState(p)} />
      </div>
      <p className="text-[16px] leading-6 font-semibold">
        {p.price_position_vs_avg_rival == null ? "No rival price yet" : `${priceVsRivals(p.price_position_vs_avg_rival)}${Math.abs(p.price_position_vs_avg_rival) < 0.5 ? " with rivals" : " rivals"}`}
      </p>
      <div className="border-t border-ink/20 pt-4 mt-auto flex flex-wrap items-center justify-between gap-3 text-[15px]">
        <span className="text-ink/80">Checked {timeAgo(p.last_checked)}</span>
        <Telegram p={p} />
      </div>
    </div>
  );
}
