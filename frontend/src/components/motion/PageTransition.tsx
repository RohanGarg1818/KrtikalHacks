"use client";

import { animate } from "motion/react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { EASE, prefersReducedMotion } from "@/lib/motion";

const WIPE_MS = 300;
const COVERED = "inset(0% 0% 0% 0%)";
const BELOW = "inset(100% 0% 0% 0%)";
const ABOVE = "inset(0% 0% 100% 0%)";

/**
 * Slate Blue colour wipe between routes: 300ms up to cover, navigate, then 300ms up
 * and away once the new route has rendered. Internal link clicks are intercepted in
 * the capture phase and default-prevented (Next's <Link> then skips them); back/forward, modified clicks,
 * new tabs, hash links and same-path query changes navigate normally. Reduced motion:
 * no wipe at all. Only clip-path is animated.
 */
export default function PageTransition() {
  const router = useRouter();
  const pathname = usePathname();
  const panel = useRef<HTMLDivElement>(null);
  const pending = useRef<string | null>(null);
  const fallback = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reveal = () => {
    const el = panel.current;
    if (!el || !pending.current) return;
    pending.current = null;
    if (fallback.current) clearTimeout(fallback.current);
    animate(el, { clipPath: [COVERED, ABOVE] }, { duration: WIPE_MS / 1000, ease: EASE }).then(() => {
      el.style.visibility = "hidden";
      el.style.clipPath = BELOW;
    });
  };

  // New route rendered: uncover on the next frame so it has painted underneath.
  useEffect(() => {
    if (!pending.current) return;
    const id = requestAnimationFrame(reveal);
    return () => cancelAnimationFrame(id);
  }, [pathname]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if (prefersReducedMotion() || pending.current) return;
      const a = (e.target as Element | null)?.closest?.("a");
      if (!a || a.target === "_blank" || a.hasAttribute("download") || a.dataset.noTransition !== undefined) return;
      const href = a.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin || url.pathname === location.pathname) return;

      const el = panel.current;
      if (!el) return;
      // preventDefault alone is enough: Next <Link> skips defaultPrevented clicks, and other
      // listeners (menus closing on navigation, analytics) still see the event.
      e.preventDefault();
      const dest = url.pathname + url.search + url.hash;
      pending.current = dest;
      el.style.visibility = "visible";
      animate(el, { clipPath: [BELOW, COVERED] }, { duration: WIPE_MS / 1000, ease: EASE }).then(() => {
        router.push(dest);
        // Never leave the screen covered if the route is slow or fails.
        fallback.current = setTimeout(reveal, 4000);
      });
    };
    window.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("click", onClick, true);
      if (fallback.current) clearTimeout(fallback.current);
    };
  }, [router]);

  return (
    <div
      ref={panel}
      aria-hidden
      className="fixed inset-0 z-[3000] bg-slate pointer-events-none"
      style={{ clipPath: BELOW, visibility: "hidden", willChange: "clip-path" }}
    />
  );
}
