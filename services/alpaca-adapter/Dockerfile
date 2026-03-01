FROM node:20-alpine AS builder
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY packages ./packages
COPY services/alpaca-adapter ./services/alpaca-adapter
RUN npm install -g pnpm && pnpm install
RUN pnpm --filter "@alpaca-rl/config" --filter "@alpaca-rl/contracts" --filter "@alpaca-rl/observability" build
RUN pnpm --filter @alpaca-rl/alpaca-adapter build

FROM node:20-alpine
WORKDIR /workspace
COPY --from=builder /workspace ./
EXPOSE 3002
CMD ["node", "services/alpaca-adapter/dist/index.js"]
