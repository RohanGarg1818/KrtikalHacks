"use client";

/* eslint-disable @next/next/no-img-element */
import { useRouter } from "next/navigation";
import { use, useEffect, useState, type ReactNode } from "react";
import { api, useApi } from "@/lib/api";
import type { AlertRule, Competitor, Pincode, Plans, Product } from "@/lib/types";
import { ALERT_KIND_LABEL, FREQUENCY_LABEL, platformLabel } from "@/lib/format";
import ProductHeader from "@/components/ProductHeader";
import { CardSkeleton, ErrorCard, Toggle } from "@/components/ui";

const SECTIONS = [
  { id: "links", label: "Product & links" },
  { id: "competitors", label: "Competitors" },
  { id: "pincodes", label: "Pincodes & platforms" },
  { id: "frequency", label: "Check frequency" },
  { id: "rules", label: "Alert rules" },
  { id: "guardrails", label: "Price guardrails" },
  { id: "danger", label: "Pause or delete" },
];

/* ---------- Settings-frame primitives (node 4:579) ---------- */

/** Card: linen, 2px ink, 20px radius, 6px shadow, 26px padding, Fraunces 32/40 title + 16px gap. */
function Panel({ id, title, hint, children }: { id: string; title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="card p-[26px] scroll-mt-24 min-w-0">
      <div className="pb-4">
        <h2 className="text-[28px] sm:text-[32px] leading-10 tracking-[-0.64px]">{title}</h2>
        {hint && <p className="text-[15px] leading-[22.5px] text-ink/80 mt-1">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

/** Labelled input: 14px semibold label, 8px gap, 48px input. */
function Field({ label, className = "", children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <label className={`flex flex-col gap-2 min-w-0 ${className}`}>
      <span className="text-[14px] leading-5 font-semibold">{label}</span>
      {children}
    </label>
  );
}
const INPUT = "input h-12 px-[18px] text-[16px] font-normal";

function Select({ value, onChange, children, className = "" }: { value: string; onChange: (v: string) => void; children: ReactNode; className?: string }) {
  return (
    <div className={`relative ${className}`}>
      <select className={`${INPUT} appearance-none pr-[42px] cursor-pointer`} value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
      <img src="/figma/product-pages/chevron.svg" alt="" width={10} height={6} className="pointer-events-none absolute right-[14px] top-1/2 -translate-y-1/2" />
    </div>
  );
}

/** Setting row: label left, control right, 1px ink/20 divider (last row has none). */
function Row({ label, sub, children }: { label: ReactNode; sub?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 pt-4 pb-[17px] border-b border-ink/20 last:border-0 last:pb-4">
      <div className="min-w-0">
        <div className="text-[16px] leading-6 font-semibold">{label}</div>
        {sub && <p className="text-[14px] leading-5 text-ink/80">{sub}</p>}
      </div>
      {children}
    </div>
  );
}

/** Toggle row: uses the shared Toggle, stretched so its label sits left and the switch right. */
function ToggleRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="pt-4 pb-[17px] border-b border-ink/20 last:border-0 last:pb-4 [&>label]:flex [&>label]:w-full [&>label]:justify-between [&>label]:text-[16px] [&>label]:leading-6">
      <Toggle checked={checked} onChange={onChange} label={label} />
    </div>
  );
}

function SaveRow({ children, status }: { children: ReactNode; status?: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-4 pt-6">{children}{status}</div>;
}

function useSaver() {
  const [state, setState] = useState<Record<string, string>>({});
  async function save(key: string, fn: () => Promise<unknown>) {
    setState((s) => ({ ...s, [key]: "Saving…" }));
    try {
      await fn();
      setState((s) => ({ ...s, [key]: "✓ Saved" }));
      setTimeout(() => setState((s) => ({ ...s, [key]: "" })), 2000);
    } catch (e) {
      setState((s) => ({ ...s, [key]: e instanceof Error ? e.message : "Failed" }));
    }
  }
  return { state, save };
}

function useActiveSection(ready: boolean) {
  const [active, setActive] = useState(SECTIONS[0].id);
  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(s.id)).filter((e): e is HTMLElement => !!e);
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (vis[0]) setActive(vis[0].target.id);
      },
      { rootMargin: "-20% 0px -60% 0px" },
    );
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [ready]);
  return active;
}

const FREQUENCIES = ["3h", "6h", "12h", "daily", "weekly"];

export default function ProductSettingsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const product = useApi<Product>(`/products/${id}`);
  const plans = useApi<Plans>("/plans");
  const allPincodes = useApi<Pincode[]>("/pincodes");
  const selection = useApi<{ platforms: string[]; pincodes: string[] }>(`/products/${id}/pincodes`);
  const listings = useApi<{ platform: string; url: string | null }[]>(`/products/${id}/listings`);
  const competitors = useApi<Competitor[]>(`/products/${id}/competitors`);
  const rules = useApi<AlertRule[]>(`/products/${id}/alert-rules`);
  const { state, save } = useSaver();
  const active = useActiveSection(!!product.data);

  const [form, setForm] = useState<Partial<Product>>({});
  const [links, setLinks] = useState<Record<string, string>>({});
  const [codes, setCodes] = useState<Set<string>>(new Set());
  const [platforms, setPlatforms] = useState<Set<string>>(new Set());
  const [ruleList, setRuleList] = useState<AlertRule[]>([]);
  const [plain, setPlain] = useState("");
  const [rival, setRival] = useState({ name: "", platform: "blinkit" });
  const [suggestions, setSuggestions] = useState<Omit<Competitor, "id" | "product_id">[]>([]);

  useEffect(() => { if (product.data) setForm(product.data); }, [product.data]);
  useEffect(() => { if (listings.data) setLinks(Object.fromEntries(listings.data.map((l) => [l.platform, l.url ?? ""]))); }, [listings.data]);
  useEffect(() => {
    if (selection.data) {
      setCodes(new Set(selection.data.pincodes));
      setPlatforms(new Set(selection.data.platforms));
    }
  }, [selection.data]);
  useEffect(() => { if (rules.data) setRuleList(rules.data); }, [rules.data]);

  if (product.error) return <ErrorCard error={product.error} />;

  const allPlatforms = plans.data?.platforms ?? ["blinkit", "zepto", "instamart", "amazon", "flipkart"];
  const limits = plans.data?.plans.find((p) => p.plan === plans.data?.current);
  const toggle = <T,>(set: Set<T>, v: T) => {
    const n = new Set(set);
    if (n.has(v)) n.delete(v);
    else n.add(v);
    return n;
  };
  const patch = (fields: Partial<Product>) => api(`/products/${id}`, { method: "PATCH", json: fields }).then(() => product.mutate());
  const num = (v: string) => (v === "" ? null : Number(v));
  const Status = ({ k }: { k: string }) => (state[k] ? <span className="text-[14px] font-semibold" role="status">{state[k]}</span> : null);

  return (
    <div className="flex flex-col">
      <ProductHeader productId={id} active="settings" />
      {!product.data ? (
        <CardSkeleton rows={6} />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[211px_minmax(0,1fr)] gap-8 pt-2">
          <aside className="hidden lg:block">
            <nav className="sticky top-24 flex flex-col gap-2" aria-label="Settings sections">
              {SECTIONS.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  className={`h-12 flex items-center px-4 rounded-[12px] text-[16px] leading-6 transition-colors ${
                    active === s.id ? "bg-slate text-linen font-semibold border-2 border-ink shadow-[4px_4px_0_var(--ink)]" : "font-medium hover:bg-ink/5"
                  }`}
                >
                  {s.label}
                </a>
              ))}
            </nav>
          </aside>

          <div className="flex flex-col gap-8 min-w-0 max-w-[760px]">
            <Panel id="links" title="Product & links" hint="Where this product is listed on each platform.">
              <div className="grid gap-x-6 gap-y-6 sm:grid-cols-2">
                <Field label="Name"><input className={INPUT} value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
                <Field label="Brand"><input className={INPUT} value={form.brand ?? ""} onChange={(e) => setForm({ ...form, brand: e.target.value })} /></Field>
                <Field label="Search query used by agents" className="sm:col-span-2">
                  <input className={INPUT} value={form.search_query ?? ""} onChange={(e) => setForm({ ...form, search_query: e.target.value })} />
                </Field>
                {allPlatforms.map((p) => (
                  <Field key={p} label={`${platformLabel(p)} link`}>
                    <input className={INPUT} placeholder="https://…" value={links[p] ?? ""} onChange={(e) => setLinks({ ...links, [p]: e.target.value })} />
                  </Field>
                ))}
              </div>
              <SaveRow status={<Status k="links" />}>
                <button
                  className="btn btn-primary h-12 px-[26px]"
                  onClick={() =>
                    save("links", async () => {
                      await patch({ name: form.name, brand: form.brand || null, search_query: form.search_query });
                      await api(`/products/${id}/listings`, {
                        method: "PUT",
                        json: { listings: Object.entries(links).filter(([, u]) => u.trim()).map(([platform, url]) => ({ platform, url: url.trim() })) },
                      });
                    })
                  }
                >
                  Save changes
                </button>
              </SaveRow>
            </Panel>

            <Panel id="competitors" title="Competitors" hint="Rivals tracked alongside your product at every pincode.">
              <div className="flex flex-col">
                {competitors.data?.length === 0 && <p className="text-[15px] text-ink/70 py-4 border-b border-ink/20">No rivals yet. Add one below or ask for suggestions.</p>}
                {competitors.data?.map((c) => (
                  <Row
                    key={c.id}
                    label={
                      <span className="flex flex-wrap items-center gap-3">
                        {c.name}
                        {c.confirmed ? (
                          <span className="inline-flex items-center gap-1.5 h-9 px-[14px] rounded-[12px] border-2 border-ink bg-sage text-[14px] leading-5 font-semibold">
                            <img src="/figma/product-pages/pill-check.svg" alt="" width={10} height={7} /> {platformLabel(c.platform)}
                          </span>
                        ) : (
                          <span className="inline-flex items-center h-9 px-[14px] rounded-[12px] border-2 border-ink bg-sand text-[14px] leading-5 font-semibold">
                            {platformLabel(c.platform)} · unconfirmed
                          </span>
                        )}
                      </span>
                    }
                  >
                    <div className="flex gap-3">
                      {!c.confirmed && (
                        <button className="btn btn-sage btn-sm" onClick={() => api(`/competitors/${c.id}/confirm`, { method: "POST" }).then(() => competitors.mutate())}>
                          Confirm
                        </button>
                      )}
                      <button className="btn btn-ghost btn-sm" onClick={() => api(`/competitors/${c.id}`, { method: "DELETE" }).then(() => competitors.mutate())}>
                        Remove
                      </button>
                    </div>
                  </Row>
                ))}
              </div>
              <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_180px] pt-6">
                <Field label="Rival product name">
                  <input className={INPUT} placeholder="e.g. Mother Dairy Toned Milk 500 ml" value={rival.name} onChange={(e) => setRival({ ...rival, name: e.target.value })} />
                </Field>
                <Field label="Platform">
                  <Select value={rival.platform} onChange={(v) => setRival({ ...rival, platform: v })}>
                    {allPlatforms.map((p) => <option key={p} value={p}>{platformLabel(p)}</option>)}
                  </Select>
                </Field>
              </div>
              <SaveRow>
                <button
                  className="btn btn-primary h-12 px-[26px]"
                  disabled={!rival.name.trim()}
                  onClick={() =>
                    api(`/products/${id}/competitors`, { method: "POST", json: { ...rival, search_query: rival.name, confirmed: true } }).then(() => {
                      setRival({ ...rival, name: "" });
                      competitors.mutate();
                    })
                  }
                >
                  Add rival
                </button>
                <button
                  className="btn btn-sand h-12 px-[22px]"
                  onClick={() => api<{ suggestions: typeof suggestions }>(`/products/${id}/competitors/discover`, { method: "POST", json: {} }).then((r) => setSuggestions(r.suggestions))}
                >
                  Suggest rivals
                </button>
              </SaveRow>
              {suggestions.length > 0 && (
                <div className="pt-5">
                  <p className="eyebrow text-slate mb-3">Suggestions · tap to track</p>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((s, i) => (
                      <button
                        key={i}
                        className="pill"
                        onClick={() =>
                          api(`/products/${id}/competitors`, { method: "POST", json: { ...s, confirmed: true } }).then(() => {
                            setSuggestions(suggestions.filter((_, j) => j !== i));
                            competitors.mutate();
                          })
                        }
                      >
                        + {s.name} · {platformLabel(s.platform)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </Panel>

            <Panel id="pincodes" title="Pincodes & platforms" hint={limits?.pincodes ? `Your plan allows up to ${limits.pincodes} pincodes per product.` : "Your plan has no pincode limit."}>
              <p className="text-[14px] leading-5 font-semibold mb-2">Platforms</p>
              <div className="flex flex-wrap gap-2">
                {allPlatforms.map((p) => (
                  <button key={p} className="pill" data-active={platforms.has(p)} aria-pressed={platforms.has(p)} onClick={() => setPlatforms(toggle(platforms, p))}>
                    {platforms.has(p) ? "✓ " : ""}
                    {platformLabel(p)}
                  </button>
                ))}
              </div>
              <div className="flex items-center justify-between mt-6 mb-2">
                <p className="text-[14px] leading-5 font-semibold">Pincodes</p>
                <p className="text-[14px] font-medium text-ink/80">
                  {codes.size} selected{limits?.pincodes ? ` of ${limits.pincodes}` : ""}
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 max-h-80 overflow-y-auto p-1 -m-1">
                {allPincodes.data?.map((pc) => {
                  const on = codes.has(pc.code);
                  return (
                    <label
                      key={pc.code}
                      className={`flex items-center gap-2 border-2 border-ink rounded-[12px] px-3 py-2 text-[14px] cursor-pointer transition-colors ${on ? "bg-sage/50" : "bg-linen hover:bg-ink/5"}`}
                    >
                      <input type="checkbox" className="accent-[var(--slate)] size-4 shrink-0" checked={on} onChange={() => setCodes(toggle(codes, pc.code))} />
                      <b className="font-semibold">{pc.code}</b> <span className="truncate text-ink/80">{pc.area_name}</span>
                    </label>
                  );
                })}
              </div>
              <SaveRow status={<Status k="pins" />}>
                <button
                  className="btn btn-primary h-12 px-[26px]"
                  disabled={!codes.size || !platforms.size}
                  onClick={() => save("pins", () => api(`/products/${id}/pincodes`, { method: "PUT", json: { pincodes: [...codes], platforms: [...platforms] } }).then(() => selection.mutate()))}
                >
                  Save {codes.size} pincodes
                </button>
              </SaveRow>
            </Panel>

            <Panel id="frequency" title="Check frequency" hint="Products whose prices move often can be checked more often.">
              <div className="flex flex-col">
                <Row label="How often to check">
                  <Select className="w-[200px]" value={form.check_frequency ?? "daily"} onChange={(v) => setForm({ ...form, check_frequency: v })}>
                    {FREQUENCIES.map((f) => <option key={f} value={f}>{FREQUENCY_LABEL[f]}</option>)}
                  </Select>
                </Row>
                <ToggleRow label="Check more often when prices are volatile" checked={!!form.volatile_boost} onChange={(v) => setForm({ ...form, volatile_boost: v })} />
              </div>
              <SaveRow status={<Status k="freq" />}>
                <button className="btn btn-primary h-12 px-[26px]" onClick={() => save("freq", () => patch({ check_frequency: form.check_frequency, volatile_boost: form.volatile_boost }))}>
                  Save changes
                </button>
              </SaveRow>
            </Panel>

            <Panel id="rules" title="Alert rules" hint="Write a rule in plain English, or toggle the defaults.">
              <form
                className="flex flex-col sm:flex-row gap-3 sm:items-end"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!plain.trim()) return;
                  save("parse", async () => {
                    const rule = await api<AlertRule>(`/products/${id}/alert-rules/parse`, { method: "POST", json: { text: plain } });
                    setRuleList((r) => [...r, rule]);
                    setPlain("");
                  });
                }}
              >
                <Field label="New rule" className="flex-1">
                  <input className={INPUT} placeholder="Alert me if we go out of stock in South Delhi" value={plain} onChange={(e) => setPlain(e.target.value)} />
                </Field>
                <button className="btn btn-sand h-12 px-[22px]">Add rule</button>
              </form>
              <div className="flex flex-col pt-3">
                {ruleList.map((r, i) => (
                  <Row key={i} label={r.rule_text ?? ALERT_KIND_LABEL[r.kind]} sub={`${ALERT_KIND_LABEL[r.kind] ?? r.kind}${r.threshold != null ? ` · threshold ${r.threshold}` : ""}`}>
                    <div className="flex items-center gap-4">
                      <Toggle checked={r.active} onChange={(v) => setRuleList(ruleList.map((x, j) => (j === i ? { ...x, active: v } : x)))} />
                      <button
                        className="grid place-items-center size-9 rounded-[10px] border-2 border-ink bg-linen text-[18px] font-bold hover:bg-sand transition-colors"
                        aria-label="Remove rule"
                        onClick={() => setRuleList(ruleList.filter((_, j) => j !== i))}
                      >
                        ×
                      </button>
                    </div>
                  </Row>
                ))}
              </div>
              <SaveRow status={<><Status k="rules" /><Status k="parse" /></>}>
                <button className="btn btn-primary h-12 px-[26px]" onClick={() => save("rules", () => api(`/products/${id}/alert-rules`, { method: "PUT", json: { rules: ruleList } }).then(() => rules.mutate()))}>
                  Save rules
                </button>
              </SaveRow>
            </Panel>

            <Panel id="guardrails" title="Price guardrails" hint="Recommendations can never break these limits.">
              <div className="grid gap-6 sm:grid-cols-2">
                <Field label="Cost price (₹)"><input type="number" min={0} className={INPUT} value={form.cost_price ?? ""} onChange={(e) => setForm({ ...form, cost_price: num(e.target.value) })} /></Field>
                <Field label="Floor price (₹)"><input type="number" min={0} className={INPUT} value={form.floor_price ?? ""} onChange={(e) => setForm({ ...form, floor_price: num(e.target.value) })} /></Field>
                <Field label="Minimum margin (%)"><input type="number" min={0} className={INPUT} value={form.min_margin_pct ?? ""} onChange={(e) => setForm({ ...form, min_margin_pct: Number(e.target.value) })} /></Field>
                <Field label="Max price change per day (%)"><input type="number" min={0} className={INPUT} value={form.max_change_pct ?? ""} onChange={(e) => setForm({ ...form, max_change_pct: Number(e.target.value) })} /></Field>
              </div>
              <div className="flex flex-col pt-3 mt-3 border-t border-ink/20">
                <ToggleRow label="Every action needs my approval" checked={form.approval_required ?? true} onChange={(v) => setForm({ ...form, approval_required: v })} />
              </div>
              <SaveRow status={<Status k="guard" />}>
                <button
                  className="btn btn-primary h-12 px-[26px]"
                  onClick={() =>
                    save("guard", () =>
                      patch({ cost_price: form.cost_price, floor_price: form.floor_price, min_margin_pct: form.min_margin_pct, max_change_pct: form.max_change_pct, approval_required: form.approval_required }),
                    )
                  }
                >
                  Save guardrails
                </button>
              </SaveRow>
            </Panel>

            <Panel id="danger" title="Pause or delete">
              <div className="flex flex-col">
                <Row label={product.data.paused ? "Checks are paused" : "Pause checks"} sub={product.data.paused ? "No scheduled checks run until you resume." : "Stop scheduled checks without losing history."}>
                  <div className="flex items-center gap-3">
                    <Status k="pause" />
                    <button className="btn btn-ghost h-12 px-[22px]" onClick={() => save("pause", () => patch({ paused: !product.data!.paused }))}>
                      {product.data.paused ? "▶ Resume checks" : "‖ Pause checks"}
                    </button>
                  </div>
                </Row>
                <Row label="Delete product" sub="Removes all its history. This cannot be undone.">
                  <button
                    className="btn btn-ink h-12 px-[26px]"
                    onClick={async () => {
                      if (!confirm(`Delete ${product.data!.name} and all its history? This cannot be undone.`)) return;
                      await api(`/products/${id}`, { method: "DELETE" });
                      router.push("/products");
                    }}
                  >
                    Delete product
                  </button>
                </Row>
              </div>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
