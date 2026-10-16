// Mirrors backend/app/schemas. Keep in sync when the API changes.

export type PinStatus = "in_stock" | "out_of_stock" | "price_gap" | "stale" | "not_tracked" | "failed";
export type Priority = "high" | "medium" | "low";

export interface Health {
  status: string;
  database: string;
  mock_mode: boolean;
  integrations: Record<string, boolean>;
  bot_running: boolean;
  scheduler_running: boolean;
}

export interface Me {
  profile: {
    id: string;
    name: string;
    email: string;
    business_name: string | null;
    business_type: string;
    language: string;
    timezone: string;
    default_city: string | null;
    created_at: string;
  };
  plan: string;
  usage: { products: number; pincodes: number; checks_this_week: number };
}

export interface PlanLimits {
  plan: string;
  products: number | null;
  pincodes: number | null;
  minimum_frequency_hours: number | null;
  daily_credit_budget: number | null;
}
export interface Plans { current: string; plans: PlanLimits[]; platforms: string[] }

export interface Pincode { code: string; area_name: string; city: string; lat: number; lng: number }

export interface Dashboard {
  tiles: { key: string; label: string; value: number }[];
  alerts: Alert[];
  recommendations: (Recommendation & { product_name: string | null })[];
  telegram: { connected: boolean; total: number };
}

export interface Product {
  id: string;
  user_id: string;
  name: string;
  brand: string | null;
  search_query: string;
  image_url: string | null;
  cost_price: number | null;
  min_margin_pct: number;
  max_change_pct: number;
  floor_price: number | null;
  check_frequency: string;
  volatile_boost: boolean;
  approval_required: boolean;
  paused: boolean;
  created_at: string;
}

export interface ProductCard extends Product {
  status_strip: { platform: string; pincode: string; status: string }[];
  price_position_vs_avg_rival: number | null;
  last_checked: string | null;
  telegram_connected: boolean;
}

export interface Competitor {
  id: string;
  product_id: string;
  name: string;
  platform: string;
  url: string | null;
  search_query: string | null;
  confirmed: boolean;
}

export interface HeatmapPin {
  pincode: string;
  area: string | null;
  lat: number | null;
  lng: number | null;
  status: PinStatus;
  price: number | null;
  rival_price: number | null;
  mrp: number | null;
  eta: number | null;
  checked_at: string | null;
  platform: string;
}

export interface Heatmap {
  pins: HeatmapPin[];
  summary: { in_stock: number; out_of_stock: number; price_gap: number; stale: number; total: number };
  hot_zones: { lat: number; lng: number; count: number; pincodes: string[] }[];
  platform: string | null;
  snapshot: string;
}

export interface PinDetail {
  pincode: string;
  area: string;
  city: string;
  lat: number;
  lng: number;
  platforms: {
    platform: string;
    status: string;
    seller: {
      in_stock: boolean | null;
      price: number | null;
      mrp: number | null;
      eta: number | null;
      rating: number | null;
      status: string;
      checked_at: string | null;
      run_id: string | null;
      screenshot_url: string | null;
    };
    rivals: {
      competitor_id: string;
      name: string;
      in_stock: boolean | null;
      price: number | null;
      mrp: number | null;
      eta: number | null;
      rating: number | null;
      status: string;
      checked_at: string | null;
    }[];
  }[];
}

export interface Summary { summary_text: string; evidence: Record<string, unknown>; source: string; created_at: string }

export interface Recommendation {
  id: string;
  product_id: string;
  priority: Priority | string;
  action_text: string;
  impact_text: string;
  evidence?: Record<string, unknown>;
  status?: string;
  decided_via?: string | null;
  created_at: string;
}

export interface Spark { value: number | null; sparkline: (number | null)[] }
export interface Overview {
  kpis: {
    avg_price: Spark;
    cheapest_rival: Spark;
    in_stock: { value: number; total: number; sparkline: (number | null)[] };
    rating: Spark;
  };
  summary: Summary | null;
  recommendations: Recommendation[];
}

export interface CompetitorRow {
  entity_id: string | null;
  name: string;
  is_seller: boolean;
  platform: string;
  price: number | null;
  in_stock: number;
  total: number;
  rating: number | null;
  eta_minutes: number | null;
  price_delta_pct: number | null;
  checked_at: string | null;
}

export interface WeeklyWindow { avg_price: number | null; oos_count: number; rating: number | null; search_rank: number | null }
export interface Weekly {
  platform: string | null;
  this_week: WeeklyWindow;
  last_week: WeeklyWindow;
  series: {
    days: string[];
    entities: {
      entity_id: string | null;
      name: string;
      platform: string;
      is_seller: boolean;
      prices: (number | null)[];
      in_stock: number[];
      checks: number[];
    }[];
  };
  changelog: {
    id: string;
    competitor_id: string | null;
    platform: string;
    pincode: string;
    kind: string;
    old_value: number | null;
    new_value: number | null;
    detected_at: string;
  }[];
}

export interface Reviews {
  loves: string[];
  complaints: string[];
  items: { entity_id: string | null; name: string; loves: string[]; complaints: string[]; updated_at: string }[];
}

export interface Alert {
  id: string;
  product_id: string;
  product_name: string | null;
  kind: string;
  message: string;
  evidence: Record<string, unknown>;
  created_at: string;
  read: boolean;
  sent_telegram?: boolean;
}

export interface AlertRule {
  kind: string;
  threshold: number | null;
  rule_text: string | null;
  rule_json: Record<string, unknown>;
  active: boolean;
}

export interface TelegramStatus {
  status: "not_connected" | "waiting" | "connected";
  chat_title: string | null;
  enabled: boolean;
  bot_running: boolean;
  bot_username: string | null;
  links: {
    id: string;
    chat_id: string;
    chat_title: string | null;
    alert_types: string[];
    briefing_time: string | null;
    connected_at: string;
  }[];
}

export interface LinkCode { code: string; deep_link: string; expires_at: string; product_id: string }

export interface UserSettings {
  briefing_time: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  default_thresholds: Record<string, unknown>;
  channels: Record<string, unknown>;
}

export interface ChatMessage {
  role: "user" | "assistant" | string;
  content: string;
  actions: Record<string, unknown>[];
  evidence: Record<string, unknown>[];
  created_at: string;
}
export interface Conversation { id: string; title: string; product_id: string | null; created_at: string; message_count: number }
export interface ConversationDetail { id: string; title: string; product_id: string | null; created_at: string; messages: ChatMessage[] }
export interface HelpTopic { slug: string; title: string; body: string }

export interface Run {
  id: string;
  product_id: string;
  trigger: string;
  status: string;
  total_jobs: number;
  done_jobs: number;
  failed_jobs: number;
  credits_used: number;
  started_at: string | null;
  finished_at: string | null;
}
