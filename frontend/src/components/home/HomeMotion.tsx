"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import type Lenis from "lenis";
import { useEffect, useRef, type ReactNode } from "react";
import { useLenis } from "@/components/motion/SmoothScroll";
import { FINE_POINTER_QUERY } from "@/lib/motion";

gsap.registerPlugin(ScrollTrigger, useGSAP);

const OK = "(prefers-reduced-motion: no-preference)";

/** Scroll distance (px) the "How it works" section stays pinned while its cards arrive. */
const PIN_DISTANCE = 1100;
/** Max magnetic pull (px) and how much of the cursor offset it follows. */
const MAGNET_MAX = 8;
const MAGNET_PULL = 0.25;

/**
 * Scroll/pointer motion for the marketing homepage. Wraps the page (keeping its root
 * classes) and finds its targets by data attribute, so the page itself stays a server
 * component:
 *
 * - `data-wipe`      colour-block section clip-path wipe, once, as it enters.
 * - `data-how` + `data-step` + `data-steps`
 *                    pinned, scrubbed card sequence on fine-pointer desktop; a plain
 *                    staggered reveal elsewhere.
 * - `data-parallax="<px>"` scrubbed vertical drift (desktop width only).
 * - `data-magnetic`  wrapper that leans toward the cursor (fine pointer only).
 * - `data-sticker`   one-shot wobble when it first appears and on hover.
 * - `data-marquee`   the CSS marquee speeds up with Lenis scroll velocity.
 *
 * Every initial (hidden) state is set here, after hydration, so the server HTML is
 * complete on its own. Nothing runs under reduced motion; useGSAP + matchMedia revert
 * all tweens, ScrollTriggers and pin spacers on unmount.
 */
export default function HomeMotion({ children, className }: { children: ReactNode; className?: string }) {
  const root = useRef<HTMLDivElement>(null);
  const lenis = useLenis();

  useGSAP(
    () => {
      const q = gsap.utils.selector(root);
      const mm = gsap.matchMedia();

      mm.add(
        {
          motion: OK,
          fine: `${FINE_POINTER_QUERY} and ${OK}`,
          wide: `(min-width: 1024px) and ${OK}`,
          hover: `(hover: hover) and ${OK}`,
        },
        (ctx) => {
          const { motion, fine, wide, hover } = ctx.conditions as Record<string, boolean>;
          if (!motion) return;
          const cleanups: (() => void)[] = [];
          const on = <K extends keyof HTMLElementEventMap>(el: HTMLElement, type: K, fn: (e: HTMLElementEventMap[K]) => void) => {
            el.addEventListener(type, fn);
            cleanups.push(() => el.removeEventListener(type, fn));
          };

          // Colour-block wipes: left to right, once.
          q<HTMLElement>("[data-wipe]").forEach((el) => {
            gsap.fromTo(
              el,
              { clipPath: "inset(0% 100% 0% 0%)" },
              {
                clipPath: "inset(0% 0% 0% 0%)",
                duration: 0.9,
                ease: "power3.inOut",
                clearProps: "clipPath",
                scrollTrigger: { trigger: el, start: "top 85%", once: true },
              },
            );
          });

          // How it works.
          const how = q<HTMLElement>("[data-how]")[0];
          const steps = q<HTMLElement>("[data-step]");
          if (how && steps.length) {
            if (fine) {
              const pin = ScrollTrigger.create({
                trigger: how,
                start: "top top",
                end: `+=${PIN_DISTANCE}`,
                pin: true,
                pinSpacing: true,
                anticipatePin: 1,
              });
              gsap
                .timeline({
                  scrollTrigger: {
                    trigger: how,
                    start: "top 55%",
                    end: () => pin.end - window.innerHeight * 0.15,
                    scrub: 0.6,
                    invalidateOnRefresh: true,
                  },
                })
                .from(steps, { opacity: 0, y: 72, duration: 1, stagger: 0.9, ease: "power2.out" });
            } else {
              gsap.from(steps, {
                opacity: 0,
                y: 16,
                duration: 0.45,
                stagger: 0.06,
                ease: "power2.out",
                scrollTrigger: { trigger: q("[data-steps]")[0] ?? how, start: "top 85%", once: true },
              });
            }
          }

          // Phone showcase parallax: each layer drifts ±N px across the section's pass.
          if (wide) {
            q<HTMLElement>("[data-parallax]").forEach((el) => {
              const d = Number(el.dataset.parallax) || 0;
              gsap.fromTo(
                el,
                { y: d },
                {
                  y: -d,
                  ease: "none",
                  scrollTrigger: { trigger: el.closest("section") ?? el, start: "top bottom", end: "bottom top", scrub: true },
                },
              );
            });
          }

          // Magnetic CTAs: the wrapper moves, so the inner button's own press transform is untouched.
          if (fine) {
            q<HTMLElement>("[data-magnetic]").forEach((el) => {
              on(el, "pointermove", (e) => {
                const r = el.getBoundingClientRect();
                const cx = r.left + r.width / 2 - Number(gsap.getProperty(el, "x"));
                const cy = r.top + r.height / 2 - Number(gsap.getProperty(el, "y"));
                const clamp = gsap.utils.clamp(-MAGNET_MAX, MAGNET_MAX);
                gsap.to(el, { x: clamp((e.clientX - cx) * MAGNET_PULL), y: clamp((e.clientY - cy) * MAGNET_PULL), duration: 0.35, ease: "power3.out", overwrite: true });
              });
              on(el, "pointerleave", () => {
                gsap.to(el, { x: 0, y: 0, duration: 0.7, ease: "elastic.out(1, 0.4)", overwrite: true });
              });
            });
          }

          // Stickers: wobble around their existing tilt (GSAP's transform rotate stacks on the
          // CSS `rotate`), once on first appearance and on each hover; never loops.
          q<HTMLElement>("[data-sticker]").forEach((el) => {
            const wobble = (delay = 0) => {
              if (gsap.isTweening(el)) return;
              gsap.to(el, {
                keyframes: { rotation: [0, -6, 4.5, -2.5, 1, 0], easeEach: "sine.inOut" },
                duration: 0.75,
                delay,
                ease: "none",
              });
            };
            ScrollTrigger.create({ trigger: el, start: "top 92%", once: true, onEnter: () => wobble(0.35) });
            if (hover) on(el, "pointerenter", () => wobble());
          });

          // Fonts can change section heights after the first measure.
          let alive = true;
          document.fonts?.ready.then(() => alive && ScrollTrigger.refresh());

          return () => {
            alive = false;
            cleanups.forEach((fn) => fn());
          };
        },
      );
    },
    { scope: root },
  );

  // Marquee: scroll velocity → playbackRate of the CSS animation (1–4×), easing back to 1×.
  // No Lenis under reduced motion, so the global reduced-motion rule is left alone.
  useEffect(() => {
    const el = root.current?.querySelector<HTMLElement>("[data-marquee]");
    if (!lenis || !el) return;
    let target = 1;
    let rate = 1;
    const off = lenis.on("scroll", (l: Lenis) => {
      target = Math.max(target, gsap.utils.clamp(1, 4, 1 + Math.abs(l.velocity) * 0.12));
    });
    const tick = () => {
      if (target === 1 && rate === 1) return;
      target += (1 - target) * 0.06;
      rate += (target - rate) * 0.15;
      if (target < 1.003 && Math.abs(rate - 1) < 0.003) target = rate = 1;
      for (const a of el.getAnimations()) a.playbackRate = rate;
    };
    gsap.ticker.add(tick);
    return () => {
      off();
      gsap.ticker.remove(tick);
      for (const a of el.getAnimations()) a.playbackRate = 1;
    };
  }, [lenis]);

  return (
    <div ref={root} className={className}>
      {children}
    </div>
  );
}
