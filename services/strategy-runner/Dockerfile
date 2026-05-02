ARG NODE_VERSION=20-alpine

# ── Builder ───────────────────────────────────────────────────────────
FROM node:${NODE_VERSION} AS builder
WORKDIR /workspace
RUN npm install -g pnpm@9
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY services/strategy-runner ./services/strategy-runner
RUN pnpm install --frozen-lockfile
RUN pnpm --filter "@alpaca-rl/config" \
         --filter "@alpaca-rl/contracts" \
         --filter "@alpaca-rl/observability" build
RUN pnpm --filter @alpaca-rl/strategy-runner build

# Produce a pruned, prod-only deployment for the runner.
RUN pnpm --filter @alpaca-rl/strategy-runner deploy --prod /deploy

# ── Runner ────────────────────────────────────────────────────────────
FROM node:${NODE_VERSION} AS runner

ARG BUILD_VERSION=dev
ARG GIT_SHA=unknown
ENV BUILD_VERSION=${BUILD_VERSION} \
    GIT_SHA=${GIT_SHA} \
    NODE_ENV=production

LABEL org.opencontainers.image.title="alpaca-rl-strategy-runner" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"

# `node` user (uid 1000) ships with the official image — no need to create one.
WORKDIR /app
COPY --from=builder --chown=node:node /deploy/dist ./dist
COPY --from=builder --chown=node:node /deploy/node_modules ./node_modules
COPY --from=builder --chown=node:node /deploy/package.json ./package.json

USER node
EXPOSE 3007

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O- http://127.0.0.1:3007/runner/health || exit 1

CMD ["node", "dist/index.js"]
