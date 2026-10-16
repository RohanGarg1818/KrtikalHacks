"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { platformLabel } from "@/lib/format";
import type { Pincode, Plans, Product } from "@/lib/types";

interface Suggestion { name: string; platform: string; url: string | null; search_query: string | null; confirmed: boolean }

/** Add product → confirm competitors → pick pincodes → first check. */
export default function AddProductDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const plans = useApi<Plans>("/plans");
  const pincodes = useApi<Pincode[]>("/pincodes");
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [brand, setBrand] = useState("");
  const [product, setProduct] = useState<Product | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [platforms, setPlatforms] = useState<Set<string>>(new Set(["blinkit"]));
  const [codes, setCodes] = useState<Set<string>>(new Set());

  const limit = plans.data?.plans.find((p) => p.plan === plans.data?.current)?.pincodes ?? null;

  async function run<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function createProduct() {
    const isLink = /^https?:\/\//.test(input.trim());
    const name = isLink ? decodeURIComponent(input.split("/").filter(Boolean).pop() ?? "New product").replace(/[-_]/g, " ") : input.trim();
    await run(async () => {
      const p = await api<Product>("/products", {
        method: "POST",
        json: { name, brand: brand || null, search_query: name },
      });
      setProduct(p);
      const found = await api<{ suggestions: Suggestion[] }>(`/products/${p.id}/competitors/discover`, { method: "POST", json: {} });
      setSuggestions(found.suggestions);
      setPicked(new Set(found.suggestions.map((_, i) => i).slice(0, 3)));
      setStep(2);
    });
  }

  async function saveCompetitors() {
    if (!product) return;
    await run(async () => {
      for (const i of picked) {
        await api(`/products/${product.id}/competitors`, { method: "POST", json: { ...suggestions[i], confirmed: true } });
      }
      setStep(3);
    });
  }

  async function finish() {
    if (!product) return;
    await run(async () => {
      await api(`/products/${product.id}/pincodes`, {
        method: "PUT",
        json: { platforms: [...platforms], pincodes: [...codes] },
      });
      await api(`/products/${product.id}/runs`, { method: "POST", json: {} });
      router.push(`/heatmap?product=${product.id}`);
    });
  }

  const toggle = <T,>(set: Set<T>, v: T) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    return next;
  };

  const STEP_TITLES = ["Add a product", "Confirm competitors", "Where do you sell?"];

  return (
    <div className="fixed inset-0 z-[2000] bg-ink/60 grid place-items-center p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-product-title"
        className="card w-full max-w-[560px] p-[26px] max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2" aria-label={`Step ${step} of 3`}>
            {[1, 2, 3].map((n) => (
              <span
                key={n}
                className={`grid place-items-center size-7 rounded-full border-2 border-ink font-display text-[13px] leading-none ${
                  n < step ? "bg-sage" : n === step ? "bg-sand shadow-[2px_2px_0_var(--ink)]" : "bg-linen text-ink/60"
                }`}
              >
                {n < step ? "✓" : n}
              </span>
            ))}
            <span className="eyebrow text-slate ml-2">Step {step} of 3</span>
          </div>
          <button
            className="grid place-items-center size-9 rounded-[10px] border-2 border-ink bg-linen text-[20px] leading-none font-bold hover:bg-sand transition-colors"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <h2 id="add-product-title" className="text-[32px] leading-10 tracking-[-0.64px] mt-5">{STEP_TITLES[step - 1]}</h2>

        {step === 1 && (
          <>
            <p className="text-[16px] leading-6 text-ink/80 mt-1">Paste a product link or type its name.</p>
            <div className="flex flex-col gap-5 mt-6">
              <label className="flex flex-col gap-2">
                <span className="text-[14px] leading-5 font-semibold">Product link or name</span>
                <input className="input h-12 px-[18px] text-[16px] font-normal" placeholder="Amul Taaza Toned Milk 500 ml" value={input} onChange={(e) => setInput(e.target.value)} autoFocus />
              </label>
              <label className="flex flex-col gap-2">
                <span className="text-[14px] leading-5 font-semibold">Brand <span className="font-medium text-ink/60">(optional)</span></span>
                <input className="input h-12 px-[18px] text-[16px] font-normal" placeholder="Amul" value={brand} onChange={(e) => setBrand(e.target.value)} />
              </label>
            </div>
            <button className="btn btn-primary h-12 mt-6 w-full" disabled={!input.trim() || busy} onClick={createProduct}>
              {busy ? "Finding competitors…" : "Find competitors →"}
            </button>
          </>
        )}

        {step === 2 && (
          <>
            <p className="text-[16px] leading-6 text-ink/80 mt-1">We found similar products. Pick the ones to track.</p>
            <ul className="flex flex-col gap-3 mt-6 stagger">
              {suggestions.length === 0 && <li className="text-[15px] text-ink/70">No suggestions found — you can add rivals later in settings.</li>}
              {suggestions.map((s, i) => (
                <li key={i}>
                  <label
                    className={`flex items-center gap-3 border-2 border-ink rounded-[12px] px-4 py-3 cursor-pointer transition-colors ${
                      picked.has(i) ? "bg-sage/50 shadow-[3px_3px_0_var(--ink)]" : "bg-linen hover:bg-ink/5"
                    }`}
                  >
                    <input type="checkbox" checked={picked.has(i)} onChange={() => setPicked(toggle(picked, i))} className="accent-[var(--slate)] size-4 shrink-0" />
                    <span className="font-semibold text-[15px] flex-1 min-w-0">{s.name}</span>
                    <span className="chip bg-linen shrink-0">{platformLabel(s.platform)}</span>
                  </label>
                </li>
              ))}
            </ul>
            <button className="btn btn-primary h-12 mt-6 w-full" disabled={busy} onClick={saveCompetitors}>
              {busy ? "Saving…" : `Track ${picked.size} competitor${picked.size === 1 ? "" : "s"} →`}
            </button>
          </>
        )}

        {step === 3 && (
          <>
            <p className="text-[14px] leading-5 font-semibold mt-6 mb-2">Platforms</p>
            <div className="flex flex-wrap gap-2">
              {(plans.data?.platforms ?? ["blinkit", "zepto", "instamart"]).map((p) => (
                <button key={p} type="button" className="pill" data-active={platforms.has(p)} aria-pressed={platforms.has(p)} onClick={() => setPlatforms(toggle(platforms, p))}>
                  {platforms.has(p) ? "✓ " : ""}
                  {platformLabel(p)}
                </button>
              ))}
            </div>
            <div className="flex items-center justify-between mt-6 mb-2">
              <p className="text-[14px] leading-5 font-semibold">Pincodes</p>
              <span className={`text-[14px] font-medium ${limit != null && codes.size > limit ? "text-ink font-semibold bg-sand px-2 rounded-md" : "text-ink/80"}`}>
                {codes.size} selected{limit ? ` · plan allows ${limit}` : ""}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-60 overflow-y-auto p-1 -m-1">
              {pincodes.data?.map((pc) => (
                <label
                  key={pc.code}
                  className={`flex items-center gap-2 border-2 border-ink rounded-[12px] px-3 py-2 text-[14px] cursor-pointer transition-colors ${codes.has(pc.code) ? "bg-sage/50" : "bg-linen hover:bg-ink/5"}`}
                >
                  <input type="checkbox" checked={codes.has(pc.code)} onChange={() => setCodes(toggle(codes, pc.code))} className="accent-[var(--slate)] size-4 shrink-0" />
                  <b className="font-semibold">{pc.code}</b> <span className="truncate text-ink/80">{pc.area_name}</span>
                </label>
              ))}
            </div>
            <button
              className="btn btn-primary h-12 mt-6 w-full"
              disabled={busy || !codes.size || !platforms.size || (limit != null && codes.size > limit)}
              onClick={finish}
            >
              {busy ? "Starting first check…" : "Start first check →"}
            </button>
          </>
        )}

        {error && <p className="text-[14px] font-semibold mt-4 bg-sand border-2 border-ink rounded-[12px] px-4 py-3" role="alert">{error}</p>}
      </div>
    </div>
  );
}
