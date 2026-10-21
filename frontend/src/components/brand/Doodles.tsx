import type { CSSProperties } from "react";

/** Original hand-drawn marker doodles (24×24, black outline, optional candy fill). */
export type DoodleName = "star" | "squiggle" | "heart" | "leaf" | "moon" | "note" | "face" | "glass" | "burst";

function burstPoints(points = 12, outer = 11, inner = 6.2): string {
  return Array.from({ length: points * 2 }, (_, i) => {
    const r = i % 2 ? inner : outer;
    const a = (Math.PI * i) / points - Math.PI / 2;
    return `${(12 + r * Math.cos(a)).toFixed(2)},${(12 + r * Math.sin(a)).toFixed(2)}`;
  }).join(" ");
}

export function Doodle({ name, fill = "none", className = "", style }: { name: DoodleName; fill?: string; className?: string; style?: CSSProperties }) {
  const common = { stroke: "currentColor", strokeWidth: 2.2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg viewBox="0 0 24 24" className={className} style={style} aria-hidden focusable="false">
      {name === "star" && <path {...common} fill={fill} d="M12 2.8l2.7 5.7 6 .8-4.4 4.1 1.1 6-5.4-3-5.5 3 1.2-6-4.4-4.1 6-.8z" />}
      {name === "squiggle" && <path {...common} fill="none" d="M2 14c2.4-4.2 4.6-4.2 6.2 0s3.6 4.2 6 0 4.4-4.2 7.8 0" />}
      {name === "heart" && (
        <g {...common}>
          <path fill={fill} d="M12 20.5S3.4 15.1 3.4 9.3a4.3 4.3 0 0 1 8.6-1.9 4.3 4.3 0 0 1 8.6 1.9C20.6 15.1 12 20.5 12 20.5z" />
          <path fill="none" d="M9.3 12.6q2.7 2.2 5.4 0" />
          <circle cx="9.6" cy="10" r=".6" fill="currentColor" />
          <circle cx="14.4" cy="10" r=".6" fill="currentColor" />
        </g>
      )}
      {name === "leaf" && <g {...common}><path fill={fill} d="M5 19C5 10.2 11 4.6 20 4c-.5 9-6.2 15-15 15z" /><path fill="none" d="M5 19l8.5-8.5" /></g>}
      {name === "moon" && <path {...common} fill={fill} d="M15.6 3.4A8.6 8.6 0 1 0 20.6 15a7 7 0 0 1-5-11.6z" />}
      {name === "note" && (
        <g {...common}>
          <path fill="none" d="M9 17.5V5.6l10-2.1v12" />
          <circle cx="6.6" cy="17.6" r="2.5" fill={fill} />
          <circle cx="16.6" cy="15.5" r="2.5" fill={fill} />
        </g>
      )}
      {name === "face" && (
        <g {...common}>
          <circle cx="12" cy="12" r="9" fill={fill} />
          <path fill="none" d="M8 13.5q4 3.6 8 0" />
          <path fill="none" d="M9 9.2v.6M15 9.2v.6" />
        </g>
      )}
      {name === "glass" && (
        <g {...common}>
          <path fill={fill} d="M6 6h12l-1.6 13.4a2 2 0 0 1-2 1.8H9.6a2 2 0 0 1-2-1.8z" />
          <path fill="#fff" d="M9 10.2l2.8-.6.6 2.8-2.8.6zM12.6 13l2.6.4-.4 2.6-2.6-.4z" />
          <path fill="none" d="M14.2 6l2.6-3.4" />
        </g>
      )}
      {name === "burst" && <polygon {...common} fill={fill} points={burstPoints()} />}
    </svg>
  );
}

type Spot = { name: DoodleName; fill: string; top: string; left?: string; right?: string; size: number; dur: number; delay: number };

// Edge positions so doodles frame the content instead of covering it.
const SPOTS: Spot[] = [
  { name: "star", fill: "#ffd84d", top: "14%", left: "1.5%", size: 34, dur: 3.6, delay: -0.4 },
  { name: "squiggle", fill: "none", top: "34%", right: "1.2%", size: 40, dur: 4.4, delay: -1.7 },
  { name: "heart", fill: "#ff9ec7", top: "58%", left: "1%", size: 34, dur: 3.9, delay: -2.6 },
  { name: "leaf", fill: "#8ce8b0", top: "80%", right: "2%", size: 32, dur: 4.8, delay: -0.9 },
  { name: "moon", fill: "#b9a6ff", top: "88%", left: "3%", size: 28, dur: 3.3, delay: -3.1 },
  { name: "note", fill: "#8fd3ff", top: "22%", right: "3%", size: 30, dur: 4.1, delay: -1.2 },
  { name: "glass", fill: "#ffd84d", top: "46%", right: "0.6%", size: 32, dur: 4.6, delay: -2.2 },
  { name: "burst", fill: "#ff8a3d", top: "70%", left: "2.2%", size: 30, dur: 3.7, delay: -0.2 },
];

/** Decorative doodles fixed around the page edges; each bobs and rotates out of sync. */
export function FloatingDoodles() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[30] hidden xl:block">
      {SPOTS.map((s, i) => (
        <span
          key={i}
          className="ss-float absolute text-ink"
          style={{ top: s.top, left: s.left, right: s.right, width: s.size, height: s.size, "--float-dur": `${s.dur}s`, "--float-delay": `${s.delay}s` } as CSSProperties}
        >
          <Doodle name={s.name} fill={s.fill} className="size-full" />
        </span>
      ))}
    </div>
  );
}

/** Original mascot: a cheerful orange with a leaf, little limbs and a waving arm. */
export function Mascot({ pose = "wave", className = "" }: { pose?: "wave" | "walk" | "peek"; className?: string }) {
  return (
    <svg viewBox="0 0 120 150" className={`ss-bounce ${className}`} aria-hidden focusable="false">
      <g stroke="#111" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
        {/* legs */}
        {pose !== "peek" && (
          <g className={pose === "walk" ? "ss-walk" : undefined}>
            <path d="M48 112l-6 22h-7" fill="none" />
            <path d="M72 112l6 22h7" fill="none" />
          </g>
        )}
        {/* left arm */}
        <path d="M24 78c-9 4-13 10-14 17" fill="none" />
        {/* waving right arm */}
        <g className={pose === "wave" ? "ss-wave" : undefined} style={{ transformOrigin: "96px 72px" }}>
          <path d="M96 72c9-6 12-14 13-22" fill="none" />
          <circle cx="109.5" cy="47" r="4.5" fill="#fff8ec" />
        </g>
        {/* body */}
        <circle cx="60" cy="76" r="40" fill="#ff8a3d" />
        <path d="M44 52q6-6 14-6" fill="none" stroke="#fff8ec" strokeWidth="4" />
        {/* stem + leaf */}
        <path d="M60 36c0-6 1-10 4-13" fill="none" />
        <path d="M64 24c8-8 18-8 24-4-6 8-15 10-24 4z" fill="#8ce8b0" />
        {/* face */}
        <circle cx="47" cy="74" r="4" fill="#111" stroke="none" />
        <circle cx="73" cy="74" r="4" fill="#111" stroke="none" />
        <circle cx="48.4" cy="72.6" r="1.3" fill="#fff" stroke="none" />
        <circle cx="74.4" cy="72.6" r="1.3" fill="#fff" stroke="none" />
        <ellipse cx="38" cy="85" rx="5" ry="3" fill="#ff9ec7" stroke="none" />
        <ellipse cx="82" cy="85" rx="5" ry="3" fill="#ff9ec7" stroke="none" />
        <path d="M51 86q9 9 18 0" fill="#111" />
      </g>
    </svg>
  );
}
