"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

const SELECTOR = "main section, main > div > *";

/**
 * Scroll reveals: each block fades in and rises 40px over 600ms when 20% visible,
 * children staggered 100ms, once only. Blocks are only hidden once this script runs,
 * so the page is fully visible without JavaScript or with reduced motion.
 */
export default function RevealOnScroll() {
  const pathname = usePathname();
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const seen = new WeakSet<Element>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("ss-in");
          io.unobserve(entry.target);
        }
      },
      { threshold: 0.2 },
    );
    const scan = () => {
      document.querySelectorAll(SELECTOR).forEach((el) => {
        if (seen.has(el) || el.closest(".ss-reveal") !== null && el.closest(".ss-reveal") !== el) return;
        const box = el.getBoundingClientRect();
        if (box.height === 0) return;
        seen.add(el);
        el.classList.add("ss-reveal");
        io.observe(el);
      });
    };
    scan();
    const mo = new MutationObserver(() => scan());
    mo.observe(document.querySelector("main") ?? document.body, { childList: true, subtree: false });
    return () => {
      io.disconnect();
      mo.disconnect();
    };
  }, [pathname]);
  return null;
}
