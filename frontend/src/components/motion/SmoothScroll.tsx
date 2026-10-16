"use client";

import "lenis/dist/lenis.css";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

gsap.registerPlugin(ScrollTrigger);

const LenisContext = createContext<Lenis | null>(null);

/** The active Lenis instance, or null when smooth scrolling is off (reduced motion / SSR). */
export const useLenis = () => useContext(LenisContext);

const REDUCED = "(prefers-reduced-motion: reduce)";

/**
 * Lenis smooth scrolling driven by GSAP's ticker so ScrollTrigger and Lenis share one
 * frame loop. Skipped entirely for reduced motion, and torn down if that preference
 * changes while the page is open.
 */
export default function SmoothScroll({ children }: { children: ReactNode }) {
  const [lenis, setLenis] = useState<Lenis | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    const media = window.matchMedia(REDUCED);
    let instance: Lenis | null = null;
    let tick: ((time: number) => void) | null = null;

    const start = () => {
      instance = new Lenis({
        autoRaf: false,
        lerp: 0.1,
        // Inner scrollers (chat log, tables, dropdowns, modals) keep their own scroll.
        allowNestedScroll: true,
        // In-page links glide; Lenis honours each target's CSS scroll-margin-top, which
        // already clears the sticky header, so no extra offset here.
        anchors: true,
      });
      instance.on("scroll", ScrollTrigger.update);
      tick = (time) => instance?.raf(time * 1000);
      gsap.ticker.add(tick);
      gsap.ticker.lagSmoothing(0);
      setLenis(instance);
    };

    const stop = () => {
      if (tick) gsap.ticker.remove(tick);
      instance?.destroy();
      instance = null;
      tick = null;
      gsap.ticker.lagSmoothing(500, 33);
      setLenis(null);
    };

    const sync = () => (media.matches ? stop() : !instance && start());
    sync();
    media.addEventListener("change", sync);
    return () => {
      media.removeEventListener("change", sync);
      stop();
    };
  }, []);

  // New route content changes page height; re-measure triggers after it paints.
  useEffect(() => {
    const id = requestAnimationFrame(() => ScrollTrigger.refresh());
    return () => cancelAnimationFrame(id);
  }, [pathname]);

  return <LenisContext.Provider value={lenis}>{children}</LenisContext.Provider>;
}
