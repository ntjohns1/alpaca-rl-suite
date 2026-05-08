import { z } from 'zod';
import { ConfigSchema } from '@alpaca-rl/config';

const GatewayConfigSchema = ConfigSchema.pick({
  API_GATEWAY_PORT: true,
  PROMETHEUS_PORT: true,
  JWT_SECRET: true,
  AUTH_SERVICE_URL: true,
  MARKET_INGEST_URL: true,
  PORTFOLIO_URL: true,
  ORDERS_URL: true,
  RISK_URL: true,
  BACKTEST_URL: true,
  FEATURE_BUILDER_URL: true,
  RL_TRAIN_URL: true,
  RL_INFER_URL: true,
  OTEL_EXPORTER_OTLP_ENDPOINT: true,
}).extend({
  // Default timeout for all upstream proxied requests.
  GATEWAY_DEFAULT_TIMEOUT_MS: z.coerce.number().int().positive().default(30_000),
  // RL training jobs can legitimately run for minutes; use a separate, longer deadline.
  GATEWAY_RL_TRAIN_TIMEOUT_MS: z.coerce.number().int().positive().default(300_000),
});

export type GatewayConfig = z.infer<typeof GatewayConfigSchema>;

export function loadGatewayConfig(): GatewayConfig {
  const result = GatewayConfigSchema.safeParse(process.env);
  if (!result.success) {
    const missing = result.error.issues
      .map((i) => `  ${i.path.join('.')}: ${i.message}`)
      .join('\n');
    throw new Error(`Invalid configuration:\n${missing}`);
  }
  return result.data;
}
