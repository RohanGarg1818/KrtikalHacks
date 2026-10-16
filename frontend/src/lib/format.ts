export const PLATFORM_LABEL: Record<string, string> = {
  blinkit: "Blinkit",
  zepto: "Zepto",
  instamart: "Instamart",
  amazon: "Amazon",
  flipkart: "Flipkart",
};

export const platformLabel = (p: string | null | undefined) => (p ? PLATFORM_LABEL[p] ?? p : "All platforms");

export function rupees(v: number | null | undefined, digits = 0) {
  if (v == null) return "—";
  return `₹${v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function pct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const FREQUENCY_LABEL: Record<string, string> = {
  "3h": "Every 3 hours",
  "6h": "Every 6 hours",
  "12h": "Every 12 hours",
  daily: "Daily",
  weekly: "Weekly",
};

export const ALERT_KIND_LABEL: Record<string, string> = {
  oos_any: "Out of stock",
  rival_oos: "Rival out of stock",
  price_change_pct: "Price change",
  price_gap_pct: "Price gap",
  price_gap: "Price gap",
  rating_below: "Rating drop",
  custom: "Custom rule",
};

export const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};
