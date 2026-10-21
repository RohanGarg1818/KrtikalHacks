import type { Metadata, Viewport } from "next";
import { DM_Sans, Rubik } from "next/font/google";
import { FloatingDoodles } from "@/components/brand/Doodles";
import RevealOnScroll from "@/components/brand/RevealOnScroll";
import MotionProviders from "@/components/motion/MotionProviders";
import "./globals.css";

// Chunky display (headings, with italic emphasis) + friendly sans body.
const display = Rubik({ subsets: ["latin"], variable: "--font-display", weight: ["600", "700", "800", "900"], style: ["normal", "italic"] });
const body = DM_Sans({ subsets: ["latin"], variable: "--font-body" });

export const metadata: Metadata = {
  title: { default: "ShelfSense — See your market the way shoppers do", template: "%s · ShelfSense" },
  description: "Pincode-level price and stock tracking for quick-commerce and marketplace sellers, powered by TinyFish web agents.",
};

export const viewport: Viewport = { themeColor: "#fff8ec" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${body.variable}`}>
        <FloatingDoodles />
        <RevealOnScroll />
        <MotionProviders>{children}</MotionProviders>
      </body>
    </html>
  );
}
