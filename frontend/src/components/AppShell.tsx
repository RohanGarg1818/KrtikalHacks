"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, useApi } from "@/lib/api";
import type { Alert, Health, Me, Product, ProductCard } from "@/lib/types";
import { timeAgo } from "@/lib/format";
import ActiveIndicator, { IndicatorGroup } from "./motion/ActiveIndicator";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "nav-dashboard" },
  { href: "/products", label: "Products", icon: "nav-products" },
  { href: "/heatmap", label: "Heatmaps", icon: "nav-heatmaps" },
  { href: "/help", label: "Help Centre", icon: "nav-help" },
  { href: "/settings", label: "Settings", icon: "nav-settings" },
];

/* eslint-disable @next/next/no-img-element */
function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return <img src={`/figma/shell/${name}.svg`} alt="" width={size} height={size} className="shrink-0" />;
}

export function Logo({ dark = true }: { dark?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-3">
      <span className="grid place-items-center size-10 rounded-[12px] border-2 border-ink bg-sand shadow-[3px_3px_0_var(--ink)]">
        <Icon name="logo" size={22} />
      </span>
      <span className="flex flex-col">
        <span className={`font-display text-[24px] leading-[24px] tracking-[-0.6px] ${dark ? "text-linen" : "text-ink"}`}>ShelfSense</span>
        <span className={`text-[10px] leading-[10px] font-bold tracking-[2.2px] uppercase pt-[2px] ${dark ? "text-sand" : "text-slate"}`}>
          Intelligence
        </span>
      </span>
    </Link>
  );
}

export const initials = (name?: string) =>
  (name ?? "")
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || "·";

/**
 * The nav item the user just clicked, until the route actually changes. The page wipe
 * swallows the click (capture phase), so this listens on window too; it lets the active
 * pill start sliding while the wipe is still coming in.
 */
export function usePendingHref(scope: React.RefObject<HTMLElement | null>, attr: string) {
  const pathname = usePathname();
  const [pending, setPending] = useState<{ href: string; from: string } | null>(null);
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.(`[${attr}]`);
      if (!a || !scope.current?.contains(a)) return;
      setPending({ href: a.getAttribute(attr) ?? "", from: location.pathname });
    };
    window.addEventListener("click", onClick, true);
    return () => window.removeEventListener("click", onClick, true);
  }, [scope, attr]);
  return pending && pending.from === pathname ? pending.href : null;
}

function Sidebar({ me, onNavigate }: { me?: Me; onNavigate?: () => void }) {
  const pathname = usePathname();
  const navRef = useRef<HTMLElement>(null);
  const pending = usePendingHref(navRef, "data-nav-href");
  const active = (href: string) => (pending ? pending === href : pathname.startsWith(href));
  return (
    <aside className="bg-ink border-r-2 border-ink w-[260px] h-full flex flex-col justify-between">
      <div className="flex flex-col gap-4">
        <div className="border-b-2 border-slate/30 px-6 pt-6 pb-[26px]">
          <Logo />
        </div>
        {/* The sand pill (bg, border, 4px shadow) is one shared indicator that slides between items. */}
        <IndicatorGroup>
          <nav ref={navRef} className="flex flex-col gap-2 p-4">
            {NAV.map((n) => {
              const on = active(n.href);
              return (
                <Link
                  key={n.href}
                  href={n.href}
                  data-nav-href={n.href}
                  aria-current={on ? "page" : undefined}
                  onClick={onNavigate}
                  className={
                    on
                      ? "relative flex items-center gap-3 px-[18px] py-[14px] rounded-full border-2 border-transparent"
                      : "relative flex items-center gap-3 px-[18px] py-[14px] rounded-[14px] border-2 border-transparent hover:bg-deep transition-colors"
                  }
                >
                  {on && <ActiveIndicator id="sidebar-nav" className="-inset-[2px]! rounded-full bg-sand border-2 border-ink shadow-[4px_4px_0_var(--ink)]" />}
                  <span className={`relative z-[1] grid place-items-center size-7 rounded-[8px] ${on ? "bg-ink" : "bg-deep border border-slate/40"}`}>
                    <Icon name={n.icon} />
                  </span>
                  <span className={`relative z-[1] text-[16px] leading-6 ${on ? "font-semibold text-ink" : "font-medium text-linen"}`}>{n.label}</span>
                </Link>
              );
            })}
          </nav>
        </IndicatorGroup>
      </div>
      <div className="border-t-2 border-slate/30 px-4 pt-[18px] pb-4">
        <Link href="/settings" className="flex items-center gap-3 p-2 rounded-[14px] hover:bg-deep transition-colors">
          <span className="grid place-items-center size-10 rounded-full bg-slate border-2 border-linen shadow-[3px_3px_0_var(--ink)] text-linen font-bold text-[15px]">
            {initials(me?.profile.name)}
          </span>
          <span className="flex flex-col gap-[2px] min-w-0">
            <span className="text-linen font-semibold text-[16px] leading-[22px] truncate">{me?.profile.name ?? "…"}</span>
            <span className="self-start bg-sand border border-ink rounded-[6px] px-[9px] py-[3px] text-ink font-bold text-[14px] leading-[21px] capitalize">
              {me?.plan ?? "…"}
            </span>
          </span>
        </Link>
      </div>
    </aside>
  );
}

/** Breadcrumb for the top bar, derived from the route. */
function useCrumbs(): string[] {
  const pathname = usePathname();
  const productId = pathname.match(/^\/products\/([^/]+)/)?.[1];
  const { data: product } = useApi<Product>(productId ? `/products/${productId}` : null);
  if (pathname.startsWith("/dashboard")) return ["Dashboard"];
  if (pathname === "/products") return ["Catalog", "Products"];
  if (productId) {
    const tail = pathname.split("/")[3];
    const last = tail ? tail[0].toUpperCase() + tail.slice(1) : "Overview";
    return ["Products", product?.name ?? "…", last];
  }
  if (pathname.startsWith("/heatmap")) return ["Products", "Heatmap"];
  if (pathname.startsWith("/help")) return ["Help Centre"];
  if (pathname.startsWith("/settings")) return ["Settings"];
  return [];
}

function Bell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data, mutate } = useApi<{ items: Alert[]; unread: number }>("/me/alerts?limit=8");
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <button
        className="relative grid place-items-center size-10 rounded-[12px] bg-linen border-2 border-ink press press-3"
        aria-label="Alerts"
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="bell" />
        {!!data?.unread && <span className="absolute -top-1 -right-1 size-3 rounded-full bg-sand border-2 border-ink" />}
      </button>
      {open && (
        <div className="absolute right-0 top-12 w-80 card p-4 z-[1100]" style={{ animation: "rise 200ms ease both" }}>
          <div className="flex justify-between items-center mb-2">
            <p className="font-semibold">Alerts</p>
            {!!data?.unread && (
              <button className="text-sm font-semibold underline" onClick={() => api("/me/alerts/read-all", { method: "POST" }).then(() => mutate())}>
                Mark all read
              </button>
            )}
          </div>
          <ul className="divide-y divide-ink/15 max-h-80 overflow-y-auto">
            {data?.items.length ? (
              data.items.map((a) => (
                <li key={a.id} className="py-2">
                  <Link href={`/products/${a.product_id}`} onClick={() => setOpen(false)} className="block">
                    <p className={`text-[15px] ${a.read ? "font-medium" : "font-semibold"}`}>{a.message}</p>
                    <p className="text-[13px] text-ink/70">
                      {timeAgo(a.created_at)} · {a.product_name}
                    </p>
                  </Link>
                </li>
              ))
            ) : (
              <li className="py-2 text-sm text-ink/70">No alerts yet.</li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

function TopBar({ me, onMenu }: { me?: Me; onMenu: () => void }) {
  const router = useRouter();
  const crumbs = useCrumbs();
  const { data: products } = useApi<ProductCard[]>("/products");
  const [q, setQ] = useState("");
  const connected = products?.filter((p) => p.telegram_connected).length ?? 0;
  const total = products?.length ?? 0;
  return (
    <header className="sticky top-0 z-[1000] bg-linen border-b-2 border-ink h-[72px] px-4 lg:px-10 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <button className="lg:hidden grid place-items-center size-10 rounded-[12px] border-2 border-ink press press-3" aria-label="Open menu" onClick={onMenu}>
          ☰
        </button>
        <p className="text-[16px] leading-6 truncate">
          {crumbs.map((c, i) => (
            <span key={i}>
              {i > 0 && <span className="text-ink/50 mx-2">/</span>}
              <span className={i === crumbs.length - 1 ? "font-semibold" : "font-medium"}>{c}</span>
            </span>
          ))}
        </p>
      </div>
      <form
        className="relative w-[420px] min-w-[200px] shrink hidden md:block"
        onSubmit={(e) => {
          e.preventDefault();
          const term = q.trim();
          if (!term) return;
          router.push(/^\d{6}$/.test(term) ? `/heatmap?pincode=${term}` : `/products?q=${encodeURIComponent(term)}`);
        }}
      >
        <span className="absolute left-4 top-1/2 -translate-y-1/2">
          <Icon name="search" />
        </span>
        <input className="input pl-[42px] py-[11px]" placeholder="Search products or pincodes" value={q} onChange={(e) => setQ(e.target.value)} />
      </form>
      <div className="flex items-center gap-4">
        <Link
          href={products?.[0] ? `/products/${products.find((p) => !p.telegram_connected)?.id ?? products[0].id}/telegram` : "/settings#telegram"}
          className="hidden sm:flex shrink-0 whitespace-nowrap items-center gap-2 px-[14px] py-2 rounded-[12px] bg-linen border-2 border-ink press press-3"
        >
          <span className={`size-[10px] rounded-full border border-ink ${connected ? "bg-sage" : "bg-linen"}`} />
          <span className="font-bold text-[15px] leading-[22.5px]">
            Telegram {connected}/{total}
          </span>
        </Link>
        <Bell />
        <Link
          href="/settings"
          className="grid place-items-center size-9 rounded-full bg-slate border-2 border-ink press press-3 text-linen font-bold text-[14px]"
          title={me?.profile.name}
        >
          {initials(me?.profile.name)}
        </Link>
      </div>
    </header>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const { data: me } = useApi<Me>("/me");
  const { data: health } = useApi<Health>("/health");
  const [menu, setMenu] = useState(false);
  const pathname = usePathname();
  useEffect(() => setMenu(false), [pathname]);

  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:block sticky top-0 h-screen shrink-0 z-[1001]">
        <Sidebar me={me} />
      </div>
      {menu && (
        <div className="lg:hidden fixed inset-0 z-[2000] bg-ink/50" onClick={() => setMenu(false)}>
          <div className="h-full w-[260px]" onClick={(e) => e.stopPropagation()} style={{ animation: "rise 200ms ease both" }}>
            <Sidebar me={me} onNavigate={() => setMenu(false)} />
          </div>
        </div>
      )}
      <div className="flex-1 min-w-0 flex flex-col bg-linen">
        <TopBar me={me} onMenu={() => setMenu(true)} />
        {health?.mock_mode && (
          <div className="bg-sand border-b-2 border-ink text-[13px] text-center py-1.5 font-semibold">
            Demo mode · checks, AI and Telegram are simulated until API keys are added
          </div>
        )}
        <main className="flex-1 w-full max-w-[1180px] px-4 sm:px-6 lg:px-10 pt-10 pb-16">{children}</main>
      </div>
    </div>
  );
}
