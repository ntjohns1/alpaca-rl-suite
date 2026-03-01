import { z } from 'zod';

const ConfigSchema = z.object({
  // Alpaca
  ALPACA_API_KEY: z.string().min(1),
  ALPACA_API_SECRET: z.string().min(1),
  ALPACA_BASE_URL: z.string().url().default('https://paper-api.alpaca.markets'),
  ALPACA_DATA_URL: z.string().url().default('https://data.alpaca.markets'),
  ALPACA_STREAM_URL: z.string().default('wss://stream.data.alpaca.markets'),

  // Database
  DATABASE_URL: z.string().min(1),
  TIMESCALE_ENABLED: z.coerce.boolean().default(true),

  // NATS
  NATS_URL: z.string().default('nats://localhost:4222'),

  // MinIO / S3
  S3_ENDPOINT: z.string().default('http://localhost:9000'),
  S3_BUCKET: z.string().default('alpaca-rl-artifacts'),
  S3_ACCESS_KEY: z.string().default('minioadmin'),
  S3_SECRET_KEY: z.string().default('minioadmin'),

  // Auth
  JWT_SECRET: z.string().min(32),
  JWT_EXPIRES_IN: z.string().default('24h'),

  // Service ports
  API_GATEWAY_PORT: z.coerce.number().int().default(3000),
  AUTH_PORT: z.coerce.number().int().default(3001),
  ALPACA_ADAPTER_PORT: z.coerce.number().int().default(3002),
  MARKET_INGEST_PORT: z.coerce.number().int().default(3003),
  PORTFOLIO_PORT: z.coerce.number().int().default(3004),
  ORDERS_PORT: z.coerce.number().int().default(3005),
  RISK_PORT: z.coerce.number().int().default(3006),
  STRATEGY_RUNNER_PORT: z.coerce.number().int().default(3007),
  BACKTEST_PORT: z.coerce.number().int().default(8001),
  FEATURE_BUILDER_PORT: z.coerce.number().int().default(8002),
  DATASET_BUILDER_PORT: z.coerce.number().int().default(8003),
  RL_TRAIN_PORT: z.coerce.number().int().default(8004),
  RL_INFER_PORT: z.coerce.number().int().default(8005),

  // Risk controls
  MAX_DAILY_LOSS_USD: z.coerce.number().positive().default(1000),
  MAX_POSITION_SIZE_PCT: z.coerce.number().min(0).max(1).default(0.1),
  KILL_SWITCH_ENABLED: z.coerce.boolean().default(false),

  // Trading mode
  TRADING_MODE: z.enum(['paper', 'live']).default('paper'),

  // Observability
  OTEL_EXPORTER_OTLP_ENDPOINT: z.string().default('http://localhost:4318'),
  PROMETHEUS_PORT: z.coerce.number().int().default(9090),

  // Service URLs (for inter-service calls)
  AUTH_SERVICE_URL: z.string().default('http://localhost:3001'),
  ALPACA_ADAPTER_URL: z.string().default('http://localhost:3002'),
  MARKET_INGEST_URL: z.string().default('http://localhost:3003'),
  PORTFOLIO_URL: z.string().default('http://localhost:3004'),
  ORDERS_URL: z.string().default('http://localhost:3005'),
  RISK_URL: z.string().default('http://localhost:3006'),
  RL_INFER_URL: z.string().default('http://localhost:8005'),
  BACKTEST_URL: z.string().default('http://localhost:8001'),
  FEATURE_BUILDER_URL: z.string().default('http://localhost:8002'),
});

export type Config = z.infer<typeof ConfigSchema>;

let _config: Config | null = null;

export function loadConfig(): Config {
  if (_config) return _config;

  const result = ConfigSchema.safeParse(process.env);
  if (!result.success) {
    const missing = result.error.issues
      .map((i) => `  ${i.path.join('.')}: ${i.message}`)
      .join('\n');
    throw new Error(`Invalid configuration:\n${missing}`);
  }
  _config = result.data;
  return _config;
}

export function getConfig(): Config {
  if (!_config) throw new Error('Config not loaded. Call loadConfig() first.');
  return _config;
}

export { ConfigSchema };
