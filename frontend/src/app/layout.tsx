import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";
import MotionProviders from "@/components/motion/MotionProviders";
import SmoothScroll from "@/components/motion/SmoothScroll";
import "./globals.css";

// Variable Fraunces with the SOFT/WONK axes the design uses.
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces", style: ["normal", "italic"], axes: ["SOFT", "WONK", "opsz"] });
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

export const metadata: Metadata = {
  title: "ShelfSense — See your market the way shoppers do",
  description: "Pincode-level price, stock and true checkout price tracking for quick-commerce and marketplace sellers.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${fraunces.variable} ${inter.variable}`}>
        <SmoothScroll>
          <MotionProviders>{children}</MotionProviders>
        </SmoothScroll>
      </body>
    </html>
  );
}
