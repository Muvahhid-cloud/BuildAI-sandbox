import type { NextConfig } from "next";

// The browser always calls the API same-origin via /api/*; Next.js proxies to the FastAPI
// service. This keeps the httpOnly refresh cookie first-party and avoids CORS.
// NOTE: rewrites are resolved at build time for `next build` (see infra/docker/web.Dockerfile).
const apiProxyUrl = process.env.API_PROXY_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@buildai/schema"],
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiProxyUrl}/api/:path*` }];
  },
};

export default nextConfig;
