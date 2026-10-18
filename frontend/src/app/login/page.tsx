"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { Logo } from "@/components/AppShell";
import { AUTH_ENABLED, getSupabase, safeNextPath, useAuth } from "@/lib/auth";
import { errorMessage } from "@/lib/api";

type Method = "password" | "magic";
type Intent = "signin" | "signup";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-linen flex flex-col items-center justify-center px-4 py-12">
      <div className="mb-8">
        <Logo dark={false} />
      </div>
      <div className="card w-full max-w-[440px] p-6 sm:p-8">{children}</div>
      <p className="mt-6 text-[14px] text-ink/75">
        <Link href="/" className="underline font-semibold">
          ← Back to ShelfSense
        </Link>
      </p>
    </main>
  );
}

function DemoMode({ next }: { next: string }) {
  return (
    <Shell>
      <span className="sticker">Demo mode</span>
      <h1 className="text-[32px] leading-[38px] mt-5">No login needed</h1>
      <p className="text-[16px] leading-[25px] mt-3 text-ink/85">
        This ShelfSense install runs without accounts: everyone uses one shared demo seller, and checks run
        through the simulated TinyFish agent unless API keys are configured.
      </p>
      <p className="text-[14px] leading-[22px] mt-3 text-ink/75">
        To turn on real sign-in, set <code className="font-mono text-[13px]">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
        <code className="font-mono text-[13px]">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in the frontend and{" "}
        <code className="font-mono text-[13px]">SUPABASE_JWT_SECRET</code> on the backend.
      </p>
      <Link href={next} className="btn btn-primary w-full mt-6">
        Continue to dashboard
      </Link>
    </Shell>
  );
}

function SupabaseLogin({ next }: { next: string }) {
  const router = useRouter();
  const { ready, session } = useAuth();
  const [method, setMethod] = useState<Method>("password");
  const [intent, setIntent] = useState<Intent>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (ready && session) router.replace(next);
  }, [ready, session, next, router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const client = getSupabase();
    if (!client || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const sb = await client;
      const addr = email.trim();
      if (method === "magic") {
        const { error: err } = await sb.auth.signInWithOtp({
          email: addr,
          options: { emailRedirectTo: `${window.location.origin}/login?next=${encodeURIComponent(next)}` },
        });
        if (err) throw err;
        setNotice(`We sent a sign-in link to ${addr}. Open it on this device to continue.`);
      } else if (intent === "signup") {
        const { data, error: err } = await sb.auth.signUp({
          email: addr,
          password,
          options: { emailRedirectTo: `${window.location.origin}/login?next=${encodeURIComponent(next)}` },
        });
        if (err) throw err;
        if (data.session) router.replace(next);
        else setNotice(`Check ${addr} to confirm your account, then sign in.`);
      } else {
        const { error: err } = await sb.auth.signInWithPassword({ email: addr, password });
        if (err) throw err;
        router.replace(next);
      }
    } catch (err) {
      setError(errorMessage(err, "Sign-in failed"));
    } finally {
      setBusy(false);
    }
  };

  if (ready && session) {
    return (
      <Shell>
        <p className="flex items-center gap-3 font-semibold" role="status">
          <span className="ss-spin" aria-hidden /> Signed in — taking you back…
        </p>
      </Shell>
    );
  }

  const title = method === "magic" ? "Sign in with a link" : intent === "signup" ? "Create your account" : "Sign in";
  return (
    <Shell>
      <h1 className="text-[32px] leading-[38px]">{title}</h1>
      <p className="text-[15px] mt-2 text-ink/80">See your market the way shoppers do — pincode by pincode.</p>

      <div className="flex gap-2 mt-6" role="group" aria-label="Sign-in method">
        <button type="button" className="pill flex-1" data-active={method === "password"} aria-pressed={method === "password"} onClick={() => setMethod("password")}>
          Password
        </button>
        <button type="button" className="pill flex-1" data-active={method === "magic"} aria-pressed={method === "magic"} onClick={() => setMethod("magic")}>
          Email link
        </button>
      </div>

      <form className="flex flex-col gap-4 mt-6" onSubmit={submit}>
        <label className="flex flex-col gap-1.5">
          <span className="label">Email</span>
          <input
            className="input"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@yourbrand.in"
          />
        </label>
        {method === "password" && (
          <label className="flex flex-col gap-1.5">
            <span className="label">Password</span>
            <input
              className="input"
              type="password"
              autoComplete={intent === "signup" ? "new-password" : "current-password"}
              required
              minLength={intent === "signup" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
        )}
        {error && (
          <p role="alert" className="bg-sand border-2 border-ink rounded-[12px] px-4 py-3 text-[14px] font-semibold">
            ✕ {error}
          </p>
        )}
        {notice && (
          <p role="status" className="bg-sage/30 border-2 border-ink rounded-[12px] px-4 py-3 text-[14px] font-semibold">
            ✓ {notice}
          </p>
        )}
        <button type="submit" className="btn btn-primary w-full" disabled={busy || !email.trim() || (method === "password" && !password)}>
          {busy && <span className="ss-spin border-linen/40 border-t-linen" aria-hidden />}
          {method === "magic" ? "Email me a link" : intent === "signup" ? "Create account" : "Sign in"}
        </button>
      </form>

      {method === "password" && (
        <p className="text-[14px] mt-5 text-center">
          {intent === "signin" ? "New to ShelfSense? " : "Already have an account? "}
          <button type="button" className="font-semibold underline" onClick={() => setIntent(intent === "signin" ? "signup" : "signin")}>
            {intent === "signin" ? "Create an account" : "Sign in"}
          </button>
        </p>
      )}
    </Shell>
  );
}

function LoginInner() {
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"));
  return AUTH_ENABLED ? <SupabaseLogin next={next} /> : <DemoMode next={next} />;
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
