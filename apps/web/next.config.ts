import type { NextConfig } from "next";

// The browser always calls the API same-origin via /api/*; Next.js proxies to the FastAPI
// service. This keeps the httpOnly refresh cookie first-party and avoids CORS.
// NOTE: rewrites are resolved at build time for `next build` (see infra/docker/web.Dockerfile).
const apiProxyUrl = process.env.API_PROXY_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  transpilePackages: ["@buildai/schema"],
  experimental: {
    // AI-assisted modification (Phase 5) answers synchronously; a real model call can take longer
    // than the proxy's 30 s default. Above the API's own AI timeout (120 s + one repair call).
    proxyTimeout: 300_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiProxyUrl}/api/:path*` }];
  },
};

export default nextConfig;
