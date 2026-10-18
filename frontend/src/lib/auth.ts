import type { Session, SupabaseClient, User } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

/**
 * Optional Supabase auth. With NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY set the app
 * requires a login and sends the session's access token on every API call; without them it runs in
 * "demo mode" against the backend's dev account and never shows a login wall.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const AUTH_ENABLED = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
export type ClientAuthMode = "supabase" | "demo";
export const AUTH_MODE: ClientAuthMode = AUTH_ENABLED ? "supabase" : "demo";

let clientPromise: Promise<SupabaseClient> | null = null;

/** Lazily loads the Supabase SDK (kept out of the demo-mode bundle). Null in demo mode / on the server. */
export function getSupabase(): Promise<SupabaseClient> | null {
  if (!AUTH_ENABLED || typeof window === "undefined") return null;
  clientPromise ??= import("@supabase/supabase-js").then(({ createClient }) =>
    createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    }),
  );
  return clientPromise;
}

/** Current access token (refreshed by the SDK when near expiry), or null in demo mode / signed out. */
export async function getAccessToken(): Promise<string | null> {
  const client = getSupabase();
  if (!client) return null;
  try {
    const { data } = await (await client).auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

/** Only same-origin absolute paths are allowed as post-login destinations. */
export function safeNextPath(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  if (next.startsWith("/login")) return fallback;
  return next;
}

export function loginHref(next?: string) {
  return next ? `/login?next=${encodeURIComponent(safeNextPath(next))}` : "/login";
}

let redirecting = false;

/** Sends the browser to /login, remembering where it was. No-op in demo mode or when already there. */
export function redirectToLogin() {
  if (!AUTH_ENABLED || typeof window === "undefined" || redirecting) return;
  if (window.location.pathname.startsWith("/login")) return;
  redirecting = true;
  window.location.assign(loginHref(window.location.pathname + window.location.search));
}

export async function signOut() {
  const client = getSupabase();
  if (client) await (await client).auth.signOut();
  if (typeof window !== "undefined") window.location.assign("/login");
}

export interface AuthState {
  mode: ClientAuthMode;
  /** False until the stored session has been read (always true in demo mode). */
  ready: boolean;
  session: Session | null;
  user: User | null;
  signOut: () => Promise<void>;
}

/** Live auth session. In demo mode it is immediately ready with no session. */
export function useAuth(): AuthState {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(!AUTH_ENABLED);

  useEffect(() => {
    const client = getSupabase();
    if (!client) return;
    let cancelled = false;
    let unsubscribe: (() => void) | undefined;
    client
      .then(async (sb) => {
        const { data } = await sb.auth.getSession();
        if (cancelled) return;
        setSession(data.session);
        setReady(true);
        const { data: sub } = sb.auth.onAuthStateChange((_event, next) => setSession(next));
        unsubscribe = () => sub.subscription.unsubscribe();
      })
      .catch(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, []);

  return { mode: AUTH_MODE, ready, session, user: session?.user ?? null, signOut };
}
