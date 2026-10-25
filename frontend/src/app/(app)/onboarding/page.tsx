"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage, useApi } from "@/lib/api";
import { toast } from "@/lib/toast";
import type { Me } from "@/lib/types";

const TYPES = [
  ["marketplace_seller", "Marketplace seller"],
  ["d2c_brand", "D2C brand"],
  ["brand_team", "Brand team"],
] as const;

/** First sign-in: finish the seller profile, optionally stock the store with demo products. */
export default function OnboardingPage() {
  const router = useRouter();
  const me = useApi<Me>("/me");
  const [f, setF] = useState<{ name: string; business: string; type: string; city: string; demo: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const form = f ?? {
    name: me.data?.profile.name && me.data.profile.name !== "ShelfSense user" ? me.data.profile.name : "",
    business: me.data?.profile.business_name ?? "",
    type: me.data?.profile.business_type ?? "marketplace_seller",
    city: me.data?.profile.default_city ?? "Delhi",
    demo: true,
  };
  const set = (patch: Partial<typeof form>) => setF({ ...form, ...patch });
  const ok = form.name.trim() && form.business.trim();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!ok || busy) return;
    setBusy(true);
    try {
      await api("/me", {
        method: "PATCH",
        json: { name: form.name.trim(), business_name: form.business.trim(), business_type: form.type, default_city: form.city.trim() || null },
      });
      if (form.demo) await api("/store/demo", { method: "POST" });
      toast(`Welcome, ${form.name.trim().split(/\s+/)[0]}! Your store is ready.`);
      router.replace("/store");
    } catch (err) {
      toast.error(errorMessage(err, "Could not save your profile"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[560px] flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-[40px] leading-[46px] tracking-[-1px]">Set up your store</h1>
        <p className="text-[16px] leading-6 text-ink/80">Two quick details and you&apos;re in. You can change them later in Settings.</p>
      </div>
      <form onSubmit={save} className="card p-[26px] flex flex-col gap-5">
        <label className="flex flex-col gap-1.5">
          <span className="text-[14px] font-semibold">Your name</span>
          <input id="ob-name" className="input h-12 px-4 text-[16px]" maxLength={200} value={form.name} onChange={(e) => set({ name: e.target.value })} />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-[14px] font-semibold">Business name</span>
          <input id="ob-business" className="input h-12 px-4 text-[16px]" maxLength={200} placeholder="Riya Store" value={form.business} onChange={(e) => set({ business: e.target.value })} />
        </label>
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 min-w-0">
            <span className="text-[14px] font-semibold">You are a</span>
            <select id="ob-type" className="input h-12 px-4 text-[16px] cursor-pointer" value={form.type} onChange={(e) => set({ type: e.target.value })}>
              {TYPES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5 min-w-0">
            <span className="text-[14px] font-semibold">City</span>
            <input id="ob-city" className="input h-12 px-4 text-[16px]" maxLength={100} value={form.city} onChange={(e) => set({ city: e.target.value })} />
          </label>
        </div>
        <label className="flex items-center gap-3 text-[15px]">
          <input id="ob-demo" type="checkbox" className="size-4 accent-[var(--slate)]" checked={form.demo} onChange={(e) => set({ demo: e.target.checked })} />
          Add 4 demo products to my store (ghee, atta, salt, noodles)
        </label>
        <button type="submit" className="btn btn-primary h-12" disabled={!ok || busy}>
          {busy ? "Setting up…" : "Open my store →"}
        </button>
      </form>
    </div>
  );
}
