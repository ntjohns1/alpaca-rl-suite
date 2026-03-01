FROM node:20-alpine AS builder
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY services/api-gateway ./services/api-gateway
RUN npm install -g pnpm && pnpm install
RUN pnpm --filter "@alpaca-rl/config" --filter "@alpaca-rl/contracts" --filter "@alpaca-rl/observability" build
RUN pnpm --filter @alpaca-rl/api-gateway build

FROM node:20-alpine
WORKDIR /workspace
COPY --from=builder /workspace ./
EXPOSE 3000
CMD ["node", "services/api-gateway/dist/index.js"]
