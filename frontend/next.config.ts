import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Lets a production build (e.g. for Lighthouse) run beside `next dev` without sharing `.next`.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
