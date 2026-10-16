"use client";

/* eslint-disable @next/next/no-img-element */
import { use, useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion, type Variants } from "motion/react";
import { api, useApi } from "@/lib/api";
import { toast } from "@/lib/toast";
import { EASE } from "@/lib/motion";
import type { LinkCode, Product, TelegramStatus } from "@/lib/types";
import { ALERT_KIND_LABEL, timeAgo } from "@/lib/format";
import ProductHeader from "@/components/ProductHeader";
import { CardSkeleton } from "@/components/ui";

const ALERT_TYPES = ["oos_any", "rival_oos", "price_change_pct", "price_gap_pct", "rating_below", "recommendations", "briefing"];
const LABELS: Record<string, string> = { ...ALERT_KIND_LABEL, recommendations: "New recommendations", briefing: "Morning briefing" };
const STEPS = ["Where alerts go", "Get a code", "Send it to the bot", "Choose alerts", "Test alert"];

/** Status pill from the Settings frame Telegram card (36px, 12px radius, sage = connected, sand = not). */
function StatusPill({ connected }: { connected: boolean }) {
  return connected ? (
    <span className="inline-flex items-center gap-1.5 h-9 px-[14px] rounded-[12px] border-2 border-ink bg-sage text-[14px] leading-5 font-semibold">
      <img src="/figma/product-pages/pill-check.svg" alt="" width={10} height={7} /> Connected
    </span>
  ) : (
    <span className="inline-flex items-center h-9 px-[14px] rounded-[12px] border-2 border-ink bg-sand text-[14px] leading-5 font-semibold">Not connected</span>
  );
}

const errMsg = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

/** Circle pop when it becomes current or done (keyframes replay on each state change, not on mount). */
const circle: Variants = {
  todo: { scale: 1 },
  current: { scale: [1, 1.14, 1], transition: { duration: 0.36, ease: EASE, delay: 0.18 } },
  done: { scale: [1, 1.14, 1], transition: { duration: 0.36, ease: EASE } },
};

/** Step cards cross-fade with a small slide in the direction of travel (10px keeps the 6px shadow
 *  inside the 16px mobile gutter, so no horizontal scroll mid-transition). */
const stepCard: Variants = {
  enter: (dir: number) => ({ opacity: 0, x: 10 * dir }),
  center: { opacity: 1, x: 0, transition: { duration: 0.28, ease: EASE } },
  exit: (dir: number) => ({ opacity: 0, x: -10 * dir, transition: { duration: 0.16, ease: "easeIn" } }),
};

/** Numbered stepper: sand = current, sage + check = done, linen = to do.
 *  The connector to circle n fills left→right (scaleX) once step n is reached. */
function Stepper({ step }: { step: number }) {
  return (
    <ol className="flex items-start" aria-label="Setup progress">
      {STEPS.map((label, i) => {
        const n = i + 1;
        const done = step > n;
        const current = step === n;
        return (
          <li key={label} className="flex-1 flex flex-col items-center gap-2 relative min-w-0" aria-current={current ? "step" : undefined}>
            {i > 0 && (
              <span className="absolute top-5 right-1/2 w-full h-[2px] -z-0 bg-ink/20" aria-hidden>
                <motion.span
                  className="absolute inset-0 bg-ink"
                  style={{ originX: 0 }}
                  initial={false}
                  animate={{ scaleX: step >= n ? 1 : 0 }}
                  transition={{ duration: 0.4, ease: EASE }}
                />
              </span>
            )}
            <motion.span
              variants={circle}
              initial={false}
              animate={done ? "done" : current ? "current" : "todo"}
              className={`relative z-10 grid place-items-center size-10 rounded-full border-2 border-ink font-display text-[18px] leading-none transition-colors ${
                done ? "bg-sage shadow-[3px_3px_0_var(--ink)]" : current ? "bg-sand shadow-[3px_3px_0_var(--ink)]" : "bg-linen text-ink/60"
              }`}
            >
              {done ? <img src="/figma/product-pages/pill-check.svg" alt="Done" width={14} height={11} /> : n}
            </motion.span>
            <span className={`text-center text-[14px] leading-5 px-1 hidden md:block ${current ? "font-semibold" : "font-medium text-ink/70"}`}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function StepCard({ n, title, hint, children }: { n: number; title: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <section className="card p-[26px] flex flex-col gap-5 min-w-0">
      <div>
        <p className="eyebrow text-slate">Step {n} of {STEPS.length}</p>
        <h2 className="text-[28px] sm:text-[32px] leading-10 tracking-[-0.64px] mt-1">{title}</h2>
        {hint && <p className="text-[16px] leading-6 text-ink/80 mt-1">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export default function TelegramPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const product = useApi<Product>(`/products/${id}`);
  const [chatType, setChatType] = useState<"personal" | "group">("personal");
  const [code, setCode] = useState<LinkCode | null>(null);
  const [step, setStep] = useState(1);
  const status = useApi<TelegramStatus>(`/products/${id}/telegram/status`, { refreshInterval: code && step < 4 ? 3000 : 0 });
  const [types, setTypes] = useState<Set<string>>(new Set(["oos_any", "recommendations", "briefing"]));
  const [briefing, setBriefing] = useState("08:00");
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Direction of travel for the step-card transition (adjusted during render, not in an effect).
  const [view, setView] = useState({ step, dir: 1 });
  if (view.step !== step) setView({ step, dir: step > view.step ? 1 : -1 });

  const connected = status.data?.status === "connected";
  const link = status.data?.links[0];

  useEffect(() => {
    if (connected && step < 4) {
      // Only celebrate a link made in this flow, not an already-connected product loading.
      if (code) toast("Telegram connected");
      setStep(4);
    }
  }, [connected, step, code]);
  useEffect(() => {
    if (link) {
      if (link.alert_types.length) setTypes(new Set(link.alert_types));
      if (link.briefing_time) setBriefing(link.briefing_time);
    }
  }, [link]);

  async function getCode() {
    try {
      setCode(await api<LinkCode>(`/products/${id}/telegram/link-code`, { method: "POST", json: { chat_type: chatType } }));
      setStep(3);
      toast("Link code generated");
    } catch (e) {
      toast.error(errMsg(e, "Couldn't create a link code"));
    }
  }

  const ready = status.data && product.data;
  const mock = !status.data?.enabled;

  return (
    <div className="flex flex-col">
      <ProductHeader productId={id} active="telegram" action={status.data ? <StatusPill connected={connected} /> : undefined} />
      {!ready ? (
        <CardSkeleton rows={6} />
      ) : (
        <div className="flex flex-col gap-8 max-w-[860px]">
          <p className="text-[18px] leading-[27px] font-medium text-slate -mt-2">Get alerts, a morning briefing, and approve actions with one tap.</p>

          {mock && (
            <div className="card bg-sand px-[26px] py-4 flex items-start gap-3">
              <span className="grid place-items-center size-9 shrink-0 rounded-[10px] bg-linen border-2 border-ink">
                <img src="/figma/shell/alert-bot.svg" alt="" width={16} height={16} />
              </span>
              <p className="text-[15px] leading-[22.5px]">
                <b className="font-semibold">Demo mode:</b> no bot token is set, so messages are logged instead of sent. You can simulate the bot receiving your code in step 3.
              </p>
            </div>
          )}

          <Stepper step={step} />

          <AnimatePresence mode="wait" initial={false} custom={view.dir}>
          <motion.div key={step} className="min-w-0" custom={view.dir} variants={stepCard} initial="enter" animate="center" exit="exit">
          {step === 1 && (
            <StepCard n={1} title="Choose where alerts go">
              <div className="grid sm:grid-cols-2 gap-4" role="radiogroup">
                {(["personal", "group"] as const).map((t) => {
                  const on = chatType === t;
                  return (
                    <button
                      key={t}
                      role="radio"
                      aria-checked={on}
                      onClick={() => setChatType(t)}
                      className={`text-left border-2 border-ink rounded-[16px] p-5 flex flex-col gap-1 transition-[background,box-shadow,transform] ${
                        on ? "bg-sage/50 press press-4 -translate-x-0.5 -translate-y-0.5" : "bg-linen hover:bg-ink/5"
                      }`}
                    >
                      <span className="flex items-center justify-between gap-3">
                        <span className="font-semibold text-[18px] leading-[27px]">{t === "personal" ? "Personal chat" : "Team group"}</span>
                        <span className={`size-5 rounded-full border-2 border-ink grid place-items-center ${on ? "bg-slate" : "bg-linen"}`} aria-hidden>
                          {on && <span className="size-2 rounded-full bg-linen" />}
                        </span>
                      </span>
                      <span className="text-[15px] leading-[22.5px] text-ink/80">
                        {t === "personal" ? "Just you, in a private chat with the bot." : "Add the bot to your sales or distributor group."}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div>
                <button className="btn btn-primary h-12 px-[26px]" onClick={() => setStep(2)}>Continue →</button>
              </div>
            </StepCard>
          )}

          {step === 2 && (
            <StepCard
              n={2}
              title="Get your one-time code"
              hint={<>We&apos;ll create a code that links this {chatType === "group" ? "group" : "chat"} to <b className="font-semibold text-ink">{product.data!.name}</b>. It expires in 10 minutes.</>}
            >
              <div className="flex flex-wrap gap-3">
                <button className="btn btn-primary h-12 px-[26px]" onClick={getCode}>Generate code</button>
                <button className="btn btn-ghost h-12 px-[22px]" onClick={() => setStep(1)}>Back</button>
              </div>
            </StepCard>
          )}

          {step === 3 && (
            <StepCard n={3} title="Open the bot and send the code">
              {code && (
                <>
                  <div className="flex flex-wrap items-center gap-4">
                    <motion.code
                      initial={{ opacity: 0, scale: 0.94, clipPath: "inset(0% 50% 0% 50% round 20px)" }}
                      animate={{ opacity: 1, scale: 1, clipPath: "inset(-10% -10% -10% -10% round 20px)" }}
                      transition={{ duration: 0.4, ease: EASE, delay: 0.12 }}
                      className="font-display text-[28px] sm:text-[64px] leading-none tracking-[0.08em] sm:tracking-[0.12em] whitespace-nowrap bg-linen border-2 border-ink rounded-[20px] shadow-[6px_6px_0_var(--ink)] px-5 sm:px-8 py-5">
                      {code.code}
                    </motion.code>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => {
                        const done = () => {
                          setCopied(true);
                          toast("Code copied");
                        };
                        if (navigator.clipboard) navigator.clipboard.writeText(code.code).then(done, (e) => toast.error(errMsg(e, "Couldn't copy the code")));
                        else done();
                        setTimeout(() => setCopied(false), 1500);
                      }}
                    >
                      {copied ? "✓ Copied" : "Copy"}
                    </button>
                  </div>
                  <div className="text-[16px] leading-6">
                    {code.deep_link.startsWith("http") ? (
                      <a href={code.deep_link} target="_blank" rel="noreferrer" className="btn btn-sand h-12 px-[22px]">
                        <img src="/figma/heatmaps/imgContainer14.svg" alt="" width={16} height={13} /> Open @{status.data!.bot_username} in Telegram ↗
                      </a>
                    ) : (
                      <p>
                        In Telegram, send <code className="font-semibold bg-sand/60 border border-ink/30 rounded-md px-1.5 py-0.5">{code.deep_link}</code> to the ShelfSense bot
                        {chatType === "group" ? " in your group" : ""}.
                      </p>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-4 border-t border-ink/20 pt-4">
                    <p className="text-[14px] font-medium text-ink/80 flex items-center gap-2">
                      <span className="dot-typing shrink-0 whitespace-nowrap"><span /><span /><span /></span>
                      Waiting for confirmation · expires {new Date(code.expires_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                    </p>
                    {mock && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() =>
                          api(`/products/${id}/telegram/simulate-link`, { method: "POST", json: { code: code.code, chat_type: chatType } })
                            .then(() => status.mutate())
                            .catch((e) => toast.error(errMsg(e, "Simulation failed")))
                        }
                      >
                        Simulate bot confirmation
                      </button>
                    )}
                  </div>
                </>
              )}
            </StepCard>
          )}

          {step === 4 && (
            <StepCard n={4} title="Choose your alerts">
              {link && <LinkedRow title={link.chat_title ?? link.chat_id} when={link.connected_at} />}
              <div>
                <p className="text-[14px] leading-5 font-semibold mb-3">Send me</p>
                <div className="flex flex-wrap gap-2">
                  {ALERT_TYPES.map((t) => (
                    <button
                      key={t}
                      className="pill"
                      data-active={types.has(t)}
                      aria-pressed={types.has(t)}
                      onClick={() =>
                        setTypes((s) => {
                          const n = new Set(s);
                          if (n.has(t)) n.delete(t);
                          else n.add(t);
                          return n;
                        })
                      }
                    >
                      {types.has(t) ? "✓ " : ""}
                      {LABELS[t] ?? t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-y border-ink/20 py-4">
                <label htmlFor="briefing" className="text-[16px] leading-6 font-semibold">Morning briefing time</label>
                <input id="briefing" type="time" className="input h-12 px-[18px] text-[16px] font-normal w-[176px]" value={briefing} onChange={(e) => setBriefing(e.target.value)} />
              </div>
              <div>
                <button
                  className="btn btn-primary h-12 px-[26px]"
                  onClick={() =>
                    api(`/products/${id}/telegram`, { method: "PATCH", json: { alert_types: [...types], briefing_time: briefing } })
                      .then(() => {
                        status.mutate();
                        setStep(5);
                        toast("Alerts saved");
                      })
                      .catch((e) => toast.error(errMsg(e, "Couldn't save alerts")))
                  }
                >
                  Save alerts
                </button>
              </div>
            </StepCard>
          )}

          {step === 5 && (
            <StepCard n={5} title="Send a test alert" hint="Check that messages reach the chat, then you're done.">
              {link && <LinkedRow title={link.chat_title ?? link.chat_id} when={link.connected_at} />}
              <div className="flex gap-3 flex-wrap">
                <button
                  className="btn btn-sand h-12 px-[22px]"
                  onClick={() =>
                    api<{ message: string }>(`/products/${id}/telegram/test`, { method: "POST" })
                      .then((r) => {
                        setNote(r.message);
                        toast(r.message || "Test alert sent");
                      })
                      .catch((e) => {
                        setNote(e.message);
                        toast.error(errMsg(e, "Test alert failed"));
                      })
                  }
                >
                  <img src="/figma/heatmaps/imgContainer14.svg" alt="" width={16} height={13} /> Send test alert
                </button>
                <button className="btn btn-ghost h-12 px-[22px]" onClick={() => setStep(4)}>Edit alerts</button>
                <button
                  className="btn btn-ghost h-12 px-[22px]"
                  onClick={async () => {
                    try {
                      await api(`/products/${id}/telegram`, { method: "DELETE" });
                    } catch (e) {
                      toast.error(errMsg(e, "Couldn't disconnect"));
                      return;
                    }
                    setCode(null);
                    // Refresh first, or the "connected" effect would bounce us back to step 4.
                    await status.mutate();
                    setStep(1);
                    toast("Telegram disconnected");
                  }}
                >
                  Disconnect
                </button>
              </div>
              {note && <p className="text-[15px] font-semibold bg-sage/40 border-2 border-ink rounded-[12px] px-4 py-3" role="status">{note}</p>}
            </StepCard>
          )}
          </motion.div>
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}

function LinkedRow({ title, when }: { title: string; when: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-ink/20 pb-4">
      <span className="text-[16px] leading-6 font-semibold">{title}</span>
      <StatusPill connected />
      <span className="text-[14px] font-medium text-ink/80">linked {timeAgo(when)}</span>
    </div>
  );
}
