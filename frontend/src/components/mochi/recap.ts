/**
 * "While you were away": Mochi remembers when the seller was last here, fetches what changed since
 * (/api/catch-up) and turns it into a guided recap — dashboard vitals, each product that moved, a
 * verdict on every pending recommendation (approve / skip, and why), then the alerts inbox.
 */
import { api } from "@/lib/api";
import type { TourStep } from "./script";

const LAST_SEEN_KEY = "shelfsense.mochi.lastSeen";
/** Away at least this long before Mochi offers a recap on its own. */
export const AWAY_MS = 20 * 60 * 1000;
const MAX_PRODUCTS = 4;
const MAX_RECS_PER_PRODUCT = 2;

interface ProductChange {
  product_id: string;
  name: string;
  price_change_pct: number | null;
  went_out: string[];
  came_back: string[];
  out_now: number;
  pairs_now: number;
  alerts: number;
  headline: string;
}
interface RecVerdict {
  id: string;
  product_id: string;
  product_name: string;
  kind: string;
  priority: string;
  action_text: string;
  verdict: "approve" | "skip";
  reason: string;
  is_new: boolean;
}
export interface CatchUp {
  since: string;
  now: string;
  runs: number;
  new_alerts: number;
  unread_alerts: number;
  products: ProductChange[];
  recommendations: RecVerdict[];
}

export function readLastSeen(): number | null {
  try {
    const v = Number(window.localStorage.getItem(LAST_SEEN_KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

export function writeLastSeen(at = Date.now()) {
  try {
    window.localStorage.setItem(LAST_SEEN_KEY, String(at));
  } catch {
    /* ignore */
  }
}

export function awayFor(ms: number): string {
  const min = Math.round(ms / 60000);
  if (min < 60) return `${min} min`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} hour${h === 1 ? "" : "s"}`;
  const d = Math.round(h / 24);
  return `${d} days`;
}

export function fetchCatchUp(since: number | null): Promise<CatchUp> {
  const q = since ? `?since=${encodeURIComponent(new Date(since).toISOString())}` : "";
  return api<CatchUp>(`/catch-up${q}`);
}

const short = (s: string, n = 90) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
const escapeId = (id: string) => id.replace(/["\\]/g, "");

export function recapSteps(data: CatchUp, awayLabel: string | null, name: string | null): TourStep[] {
  const DASHBOARD = /^\/dashboard\/?$/;
  const steps: TourStep[] = [];
  const moved = data.products.filter((p) => !p.headline.startsWith("steady"));
  const approve = data.recommendations.filter((r) => r.verdict === "approve");
  const skip = data.recommendations.filter((r) => r.verdict === "skip");
  const outNow = data.products.reduce((n, p) => n + p.out_now, 0);
  const when = awayLabel ? `You were away ${awayLabel}` : "Here's the last 24 hours";

  steps.push({
    id: "recap-hello",
    chapter: "dashboard",
    route: DASHBOARD,
    href: "/dashboard",
    mood: "excited",
    text: `Welcome back${name ? `, ${name}` : ""}! ${when}. Meanwhile I ran ${data.runs} check${data.runs === 1 ? "" : "s"}: ${moved.length} product${moved.length === 1 ? "" : "s"} moved, ${data.new_alerts} new alert${data.new_alerts === 1 ? "" : "s"}, and ${approve.length} thing${approve.length === 1 ? "" : "s"} I'd approve. Let me walk you through it.`,
    nextLabel: "Show me →",
  });

  if (!moved.length && !data.recommendations.length) {
    steps.push({
      id: "recap-quiet",
      chapter: "dashboard",
      route: DASHBOARD,
      href: "/dashboard",
      target: '[data-mochi="dash-tiles"]',
      mood: "happy",
      text: "Quiet shelf — prices and stock held steady. Nothing needs you right now. ☕",
    });
    return steps;
  }

  steps.push({
    id: "recap-tiles",
    chapter: "dashboard",
    route: DASHBOARD,
    href: "/dashboard",
    target: '[data-mochi="dash-tiles"]',
    mood: outNow ? "worried" : "happy",
    text: outNow
      ? `Right now you're out of stock in ${outNow} pincode × app spot${outNow === 1 ? "" : "s"} across your products. Let's see where.`
      : "Good news first: you're in stock everywhere I checked.",
  });

  // Products that moved, plus any product with an "approve" verdict, biggest movers first.
  const order: string[] = [];
  for (const p of moved) if (!order.includes(p.product_id)) order.push(p.product_id);
  for (const r of approve) if (!order.includes(r.product_id)) order.push(r.product_id);
  const byId = new Map(data.products.map((p) => [p.product_id, p]));

  for (const pid of order.slice(0, MAX_PRODUCTS)) {
    const route = new RegExp(`^/products/${pid.replace(/[^\w-]/g, "")}/?$`);
    const href = `/products/${pid}`;
    const change = byId.get(pid);
    const recs = data.recommendations.filter((r) => r.product_id === pid);
    const productName = change?.name ?? recs[0]?.product_name ?? "This product";
    if (change) {
      steps.push({
        id: `recap-p-${pid}`,
        chapter: "product",
        route,
        href,
        target: '[data-mochi="product-kpis"]',
        mood: change.went_out.length ? "worried" : change.came_back.length || (change.price_change_pct ?? 0) < 0 ? "happy" : "curious",
        text: `${short(productName, 48)}: ${short(change.headline, 160)}.${change.alerts ? ` (${change.alerts} alert${change.alerts === 1 ? "" : "s"})` : ""}`,
      });
    }
    for (const r of recs.slice(0, MAX_RECS_PER_PRODUCT)) {
      const yes = r.verdict === "approve";
      steps.push({
        id: `recap-r-${r.id}`,
        chapter: "product",
        route,
        href,
        target: [`[data-mochi-rec="${escapeId(r.id)}"]`, '[data-mochi="product-recs"]'],
        mood: yes ? "excited" : "thinking",
        text: `${yes ? "✅ Approve this" : "⏭️ Skip this one"}: “${short(r.action_text, 80)}” — ${r.reason}`,
      });
    }
  }

  if (data.unread_alerts) {
    steps.push({
      id: "recap-alerts",
      chapter: "dashboard",
      route: /^\/alerts\/?$/,
      href: "/alerts",
      target: ['[data-mochi="alerts-inbox"]', '[data-mochi="alerts-head"]'],
      mood: "curious",
      text: `${data.unread_alerts} unread alert${data.unread_alerts === 1 ? "" : "s"} are waiting here — I've already sent the important ones to Telegram.`,
    });
  }

  const extraProducts = Math.max(0, order.length - MAX_PRODUCTS);
  steps.push({
    id: "recap-done",
    chapter: "dashboard",
    route: /.*/,
    href: "/dashboard",
    mood: "love",
    text:
      `That's the recap! In short: approve ${approve.length}, skip ${skip.length}.` +
      (extraProducts ? ` ${extraProducts} more product${extraProducts === 1 ? "" : "s"} changed — they're on the Products page.` : "") +
      " Tap me anytime and pick “What happened while I was away?” to see this again.",
  });
  return steps;
}
