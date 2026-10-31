# syntax=docker/dockerfile:1
# Build context: repo root.  docker build -f infra/docker/web.Dockerfile .
FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/schema/package.json packages/schema/
RUN pnpm install --frozen-lockfile --filter @buildai/web...

FROM deps AS build
# Next.js rewrites are resolved at build time: point /api/* at the compose "api" service.
ARG API_PROXY_URL=http://api:8000
ENV API_PROXY_URL=$API_PROXY_URL NEXT_TELEMETRY_DISABLED=1
COPY apps/web apps/web
COPY packages/schema packages/schema
# Material library + fixtures are imported at build time (@data/*).
COPY data data
RUN pnpm --filter @buildai/web build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /repo/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /repo/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
