"use client";

import Link from "next/link";
import { useState } from "react";
import { useSWRConfig } from "swr";
import { api, errorMessage, useApi } from "@/lib/api";
import { rupees, timeAgo } from "@/lib/format";
import { toast } from "@/lib/toast";
import type { StoreItem } from "@/lib/types";
import { CardSkeleton, Empty, ErrorCard } from "@/components/ui";

const RESTOCK = 20;

/** My Store: the seller's own storefront. Price and stock are set here; stock 0 alerts on Telegram. */
export default function StorePage() {
  const { data, error, mutate } = useApi<StoreItem[]>("/store");
  const { mutate: mutateAll } = useSWRConfig();
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  // A stock change creates alerts and new results: refresh the bell, dashboard and product views too.
  const refreshAll = async () => {
    await mutate();
    void mutateAll((k) => typeof k === "string" && (k.startsWith("/me/alerts") || k === "/dashboard" || k.startsWith("/products")));
  };

  async function run(key: string, fn: () => Promise<void>) {
    if (busy) return;
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      toast.error(errorMessage(e, "Something went wrong"));
    } finally {
      setBusy(null);
    }
  }

  const setStock = (item: StoreItem, stock: number) =>
    run(`${item.product_id}:${stock}`, async () => {
      await api(`/store/products/${item.product_id}`, { method: "PATCH", json: { stock } });
      await refreshAll();
      if (stock === 0)
        toast(item.telegram_connected ? `${item.name} is out of stock: Telegram alert sent` : `${item.name} is out of stock. Connect Telegram to get the alert on your phone`);
      else toast(`${item.name} restocked to ${stock}`);
    });

  const loadDemo = () =>
    run("demo", async () => {
      const added = await api<StoreItem[]>("/store/demo", { method: "POST" });
      await refreshAll();
      toast(added.length ? `Added ${added.length} demo products to your store` : "Demo products are already in your store");
    });

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-wrap items-end justify-between gap-x-6 gap-y-5">
        <div className="flex flex-col gap-2 max-w-[640px]">
          <h1 className="text-[44px] leading-[48px] sm:text-[56px] sm:leading-[60px] tracking-[-1.4px]">My Store</h1>
          <p className="text-[16px] leading-6 text-ink/80">
            Your own storefront. Set price and stock here and every change shows up instantly on the heatmap and dashboard. When stock hits 0 you get an urgent Telegram alert.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <button className="btn btn-ghost h-12 px-5" disabled={!!busy} onClick={loadDemo}>
            {busy === "demo" ? "Loading…" : "Load demo store"}
          </button>
          <button className="btn btn-primary h-12 px-5" disabled={!!busy} onClick={() => setAdding((v) => !v)}>
            {adding ? "Close" : "+ Add product"}
          </button>
        </div>
      </section>

      {adding && <AddForm onDone={async () => { setAdding(false); await refreshAll(); }} />}

      {error && !data ? (
        <ErrorCard error={error} onRetry={() => mutate()} />
      ) : !data ? (
        <CardSkeleton />
      ) : data.length === 0 ? (
        <Empty title="Your store is empty">Add a product, or load the demo store to try a stock-out alert in one click.</Empty>
      ) : (
        <ul className="grid gap-5 md:grid-cols-2">
          {data.map((item) => (
            <StoreCard key={item.product_id} item={item} busy={busy} onStock={setStock} />
          ))}
        </ul>
      )}
    </div>
  );
}

function StoreCard({
  item,
  busy,
  onStock,
}: {
  item: StoreItem;
  busy: string | null;
  onStock: (item: StoreItem, stock: number) => void;
}) {
  const [draft, setDraft] = useState(String(item.stock));
  const out = item.stock === 0;
  const parsed = Number(draft);
  const valid = draft.trim() !== "" && Number.isInteger(parsed) && parsed >= 0;
  return (
    <li className={`card p-[22px] flex flex-col gap-4 ${out ? "bg-sand" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href={`/products/${item.product_id}`} className="font-semibold text-[18px] leading-[26px] hover:underline underline-offset-2 break-words">
            {item.name}
          </Link>
          <p className="text-[14px] text-ink/75">
            {item.brand ? `${item.brand} · ` : ""}
            {rupees(item.price, 2)}
            {item.mrp ? ` · MRP ${rupees(item.mrp, 2)}` : ""} · {item.pincodes.length} pincode{item.pincodes.length === 1 ? "" : "s"}
          </p>
        </div>
        <span className={`chip shrink-0 ${out ? "bg-linen" : "bg-sage"}`}>{out ? "✕ Out of stock" : `✓ ${item.stock} in stock`}</span>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[13px] font-semibold">Stock</span>
          <input
            id={`stock-${item.product_id}`}
            type="number"
            min={0}
            inputMode="numeric"
            className="input h-11 w-28 px-3 text-[15px]"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </label>
        <button className="btn btn-ghost h-11 px-4" disabled={!!busy || !valid || parsed === item.stock} onClick={() => onStock(item, parsed)}>
          Save
        </button>
        {out ? (
          <button className="btn btn-primary h-11 px-4" disabled={!!busy} onClick={() => { setDraft(String(RESTOCK)); onStock(item, RESTOCK); }}>
            {busy === `${item.product_id}:${RESTOCK}` ? "Restocking…" : `Restock ${RESTOCK}`}
          </button>
        ) : (
          <button className="btn btn-ink h-11 px-4" disabled={!!busy} onClick={() => { setDraft("0"); onStock(item, 0); }}>
            {busy === `${item.product_id}:0` ? "Updating…" : "Set stock to 0"}
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ink/15 pt-3 text-[13px]">
        <span className="text-ink/70">Updated {timeAgo(item.updated_at)}</span>
        {item.telegram_connected ? (
          <span className="font-semibold text-ink/80">Telegram connected</span>
        ) : (
          <Link href={`/products/${item.product_id}/telegram`} className="font-semibold text-slate underline underline-offset-2">
            Connect Telegram for alerts →
          </Link>
        )}
      </div>
    </li>
  );
}

function AddForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ name: "", brand: "", price: "", mrp: "", stock: "25", pincodes: "" });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const price = Number(f.price);
  const ok = f.name.trim() && price > 0 && Number.isInteger(Number(f.stock)) && Number(f.stock) >= 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ok || busy) return;
    setBusy(true);
    try {
      const pincodes = f.pincodes.split(/[\s,]+/).filter(Boolean);
      await api("/store/products", {
        method: "POST",
        json: {
          name: f.name.trim(),
          brand: f.brand.trim() || null,
          price,
          mrp: f.mrp ? Number(f.mrp) : null,
          stock: Number(f.stock),
          pincodes,
        },
      });
      toast(`${f.name.trim()} added to your store`);
      onDone();
    } catch (err) {
      toast.error(errorMessage(err, "Could not add the product"));
    } finally {
      setBusy(false);
    }
  }

  const field = (id: keyof typeof f, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="text-[13px] font-semibold">{label}</span>
      <input id={`store-${id}`} className="input h-11 px-3 text-[15px]" value={f[id]} onChange={set(id)} {...props} />
    </label>
  );

  return (
    <form onSubmit={submit} className="card p-[22px] grid gap-4 sm:grid-cols-2">
      {field("name", "Product name", { placeholder: "Amul Pure Ghee 1 L", maxLength: 300 })}
      {field("brand", "Brand (optional)", { placeholder: "Amul", maxLength: 200 })}
      {field("price", "Selling price (₹)", { type: "number", min: 0, step: "0.01" })}
      {field("mrp", "MRP (₹, optional)", { type: "number", min: 0, step: "0.01" })}
      {field("stock", "Stock", { type: "number", min: 0 })}
      {field("pincodes", "Pincodes (optional)", { placeholder: "110001, 110003 · blank = 3 Delhi pincodes" })}
      <div className="sm:col-span-2 flex justify-end">
        <button type="submit" className="btn btn-primary h-12 px-6" disabled={!ok || busy}>
          {busy ? "Adding…" : "Add to store"}
        </button>
      </div>
    </form>
  );
}
