"use client";

/* eslint-disable @next/next/no-img-element */
import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useApi } from "@/lib/api";
import type { Me, Plans } from "@/lib/types";
import AddProductDialog from "@/components/AddProductDialog";
import { CardSkeleton, Empty, ErrorCard, Skeleton, Sticker } from "@/components/ui";
import { ProductGridCard, ProductTable, coverage, platformsOf, productState, type Card, type CardState } from "@/components/products/ProductViews";

const A = "/figma/product";
const PAGE_SIZE = 8;

const FILTERS = [
  { key: "", label: "All" },
  { key: "attention", label: "Needs attention" },
  { key: "healthy", label: "Healthy" },
  { key: "paused", label: "Paused" },
  { key: "new", label: "Not checked yet" },
] as const;
type FilterKey = (typeof FILTERS)[number]["key"];

type SortKey = "attention" | "name" | "coverage" | "price" | "checked";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "attention", label: "Sort: Needs attention first" },
  { key: "name", label: "Sort: Name" },
  { key: "coverage", label: "Sort: Lowest coverage" },
  { key: "price", label: "Sort: Most expensive vs rivals" },
  { key: "checked", label: "Sort: Recently checked" },
];
const STATE_RANK: Record<CardState, number> = { attention: 0, new: 1, healthy: 2, paused: 3 };

function countBy(list: Card[]) {
  const c: Record<FilterKey, number> = { "": list.length, attention: 0, healthy: 0, paused: 0, new: 0 };
  for (const p of list) c[productState(p)]++;
  return c;
}

/** Client-side search over the one `/products` response (name, brand, search query). */
function matches(p: Card, term: string) {
  const t = term.toLowerCase();
  return [p.name, p.brand, p.search_query].some((v) => v?.toLowerCase().includes(t));
}

export default function ProductsPage() {
  return (
    <Suspense fallback={<CardSkeleton rows={5} />}>
      <ProductsView />
    </Suspense>
  );
}

function ProductsView() {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const urlQ = search.get("q") ?? "";

  const [filter, setFilter] = useState<FilterKey>("");
  const [q, setQ] = useState(urlQ);
  const [sort, setSort] = useState<SortKey>("attention");
  const [view, setView] = useState<"list" | "grid">("list");
  const [page, setPage] = useState(0);
  const [adding, setAdding] = useState(false);

  // The top-bar search navigates to /products?q=term (also while already here).
  useEffect(() => setQ(urlQ), [urlQ]);
  useEffect(() => setPage(0), [filter, q, sort]);

  const term = q.trim();

  // One request: filtering, search and counts are all derived from it.
  const { data, error, mutate } = useApi<Card[]>("/products");
  const me = useApi<Me>("/me");
  const plans = useApi<Plans>("/plans");

  const everything = useMemo(() => data ?? [], [data]);
  const searched = useMemo(() => (term ? everything.filter((p) => matches(p, term)) : everything), [everything, term]);
  const filtered = useMemo(() => (filter ? searched.filter((p) => productState(p) === filter) : searched), [searched, filter]);
  const totals = countBy(everything);
  const counts = countBy(searched);
  const platformCount = new Set(everything.flatMap(platformsOf)).size;
  const planName = me.data?.plan ?? plans.data?.current;
  const planLimit = plans.data?.plans.find((p) => p.plan === planName)?.pincodes;
  const visibleFilters = FILTERS.filter((f) => f.key !== "new" || totals.new > 0 || filter === "new");

  const rows = useMemo(() => {
    const list = [...filtered];
    list.sort((a, b) => {
      if (sort === "attention") return STATE_RANK[productState(a)] - STATE_RANK[productState(b)] || coverage(a).ratio - coverage(b).ratio || a.name.localeCompare(b.name);
      if (sort === "coverage") return coverage(a).ratio - coverage(b).ratio;
      if (sort === "price") return (b.price_position_vs_avg_rival ?? -1e9) - (a.price_position_vs_avg_rival ?? -1e9);
      if (sort === "checked") return (b.last_checked ?? "").localeCompare(a.last_checked ?? "");
      return a.name.localeCompare(b.name);
    });
    return list;
  }, [filtered, sort]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const shown = rows.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);

  function refresh() {
    void mutate();
    void me.mutate();
  }

  function clearSearch() {
    setQ("");
    router.replace(pathname);
  }

  return (
    <div className="flex flex-col gap-8">
      {/* Page header */}
      <section className="flex flex-wrap items-end justify-between gap-x-6 gap-y-5">
        <div className="flex flex-col gap-2">
          <h1 className="text-[44px] leading-[48px] sm:text-[56px] sm:leading-[60px] tracking-[-1.4px]">Products</h1>
          <p className="text-[16px] leading-[22px]">
            {data
              ? `${totals[""]} product${totals[""] === 1 ? "" : "s"} tracked across ${platformCount} platform${platformCount === 1 ? "" : "s"}.`
              : "Loading your catalogue…"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-[15px]">
          {totals.attention > 0 && (
            <Sticker className="text-[13px] leading-[19.5px] tracking-[0.65px] px-4 py-2 rounded-[8px]">{totals.attention} need attention</Sticker>
          )}
          <button className="btn btn-primary px-[26px] py-[14px] text-[15px] leading-[22.5px]" onClick={() => setAdding(true)}>
            <img src={`${A}/imgContainer.svg`} alt="" width={13.083} height={13.083} />
            Add product
          </button>
        </div>
      </section>

      {/* Summary tiles */}
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <Tile tone="bg-sage text-ink" eyebrow="Healthy" value={data ? totals.healthy : null} caption="Stock and price on track" />
        <Tile tone="bg-sand text-ink" eyebrow="Need attention" value={data ? totals.attention : null} caption="Out of stock or price gap" />
        <Tile
          tone="bg-slate text-linen"
          muted="text-linen/90"
          eyebrow="Tracked pincodes"
          value={me.data ? me.data.usage.pincodes : null}
          caption={plans.data && me.data ? (planLimit != null ? `Of ${planLimit} on your plan` : "Unlimited on your plan") : " "}
        />
      </section>

      {/* Toolbar */}
      <section className="flex flex-wrap items-center justify-between gap-4 py-1">
        <div className="flex flex-wrap items-center gap-3" role="group" aria-label="Filter products">
          {visibleFilters.map((f) => {
            const active = filter === f.key;
            return (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                aria-pressed={active}
                className={`inline-flex items-center gap-2 px-[22px] py-[10px] rounded-[12px] border-2 border-ink text-[14px] leading-[21px] font-semibold transition-[transform,box-shadow] duration-100 active:translate-x-[2px] active:translate-y-[2px] ${
                  active ? "bg-slate text-linen shadow-[4px_4px_0_var(--ink)]" : "bg-linen text-ink hover:bg-sand/40"
                }`}
              >
                {f.label}
                <span className={active ? "text-linen/90" : "text-ink/75"}>{data ? counts[f.key] : "–"}</span>
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <label className="relative inline-flex items-center">
            <span className="sr-only">Sort products</span>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              className="appearance-none bg-linen border-2 border-ink rounded-[12px] shadow-[3px_3px_0_var(--ink)] pl-[30px] pr-[44px] py-[10px] text-[14px] leading-[21px] font-semibold cursor-pointer focus:outline-none focus:ring-4 focus:ring-slate/30"
            >
              {SORTS.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
            <img src={`${A}/imgContainer1.svg`} alt="" width={9} height={5.55} className="pointer-events-none absolute right-[18px]" />
          </label>
          <div className="flex items-center" role="group" aria-label="View">
            <button
              aria-pressed={view === "list"}
              onClick={() => setView("list")}
              className={`inline-flex items-center gap-[6px] px-4 py-[10px] rounded-l-[12px] border-2 border-ink text-[14px] leading-[21px] font-semibold ${view === "list" ? "bg-slate text-linen" : "bg-linen text-ink"}`}
            >
              <img src={`${A}/imgContainer2.svg`} alt="" width={15} height={12} className={view === "list" ? "" : "invert"} />
              List
            </button>
            <button
              aria-pressed={view === "grid"}
              onClick={() => setView("grid")}
              className={`inline-flex items-center gap-[6px] pl-[14px] pr-4 py-[10px] rounded-r-[12px] border-2 border-l-0 border-ink text-[14px] leading-[21px] font-semibold ${view === "grid" ? "bg-slate text-linen" : "bg-linen text-ink"}`}
            >
              <img src={`${A}/imgContainer3.svg`} alt="" width={13.5} height={13.5} className={view === "grid" ? "invert" : ""} />
              Grid
            </button>
          </div>
        </div>
      </section>

      {term && (
        <div className="flex items-center gap-3 -mt-3 text-[15px]">
          <span>
            Results for <strong>&ldquo;{term}&rdquo;</strong>
          </span>
          <button className="underline underline-offset-4 font-semibold" onClick={clearSearch}>
            Clear search
          </button>
        </div>
      )}

      {/* Products */}
      {error ? (
        <ErrorCard error={error} onRetry={() => mutate()} />
      ) : !data ? (
        <CardSkeleton rows={6} />
      ) : rows.length === 0 ? (
        <Empty title="No products match">
          {term || filter ? "Try another filter or search." : "Add your first product to start tracking it."}
          <div>
            <button className="btn btn-primary btn-sm mt-4" onClick={() => setAdding(true)}>
              Add product
            </button>
          </div>
        </Empty>
      ) : (
        <>
          {view === "list" && (
            <div className="hidden md:block">
              <ProductTable rows={shown} />
            </div>
          )}
          <div className={`grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 stagger ${view === "list" ? "md:hidden" : ""}`}>
            {shown.map((p) => (
              <ProductGridCard key={p.id} p={p} />
            ))}
          </div>

          {/* Pagination */}
          <section className="flex flex-wrap items-center justify-between gap-4 pt-1">
            <p className="text-[15px] leading-[22.5px] font-medium">
              Showing {shown.length} of {rows.length} product{rows.length === 1 ? "" : "s"}
            </p>
            <div className="flex items-center gap-3">
              <button className="btn btn-ghost px-[18px] py-[10px] text-[14px] leading-[21px]" disabled={current === 0} onClick={() => setPage(current - 1)}>
                Previous
              </button>
              <button className="btn btn-ghost px-[18px] py-[10px] text-[14px] leading-[21px]" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
                Next
              </button>
            </div>
          </section>
        </>
      )}

      {adding && (
        <AddProductDialog
          onClose={() => {
            setAdding(false);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function Tile({ tone, muted = "", eyebrow, value, caption }: { tone: string; muted?: string; eyebrow: string; value: number | null; caption: string }) {
  return (
    <div className={`${tone} border-2 border-ink rounded-[20px] shadow-[6px_6px_0_var(--ink)] h-[200px] p-6 flex flex-col min-w-0`}>
      <p className={`text-[14px] leading-[21px] font-semibold tracking-[0.7px] uppercase ${muted}`}>{eyebrow}</p>
      {value == null ? (
        <Skeleton className="h-[72px] w-20 mt-4 opacity-30" />
      ) : (
        <p className="font-display text-[72px] leading-[72px] mt-4">{value}</p>
      )}
      <p className={`text-[15px] leading-[22.5px] font-medium mt-auto ${muted}`}>{caption}</p>
    </div>
  );
}
