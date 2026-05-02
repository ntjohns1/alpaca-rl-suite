import client from 'prom-client';

// Collect default Node.js process metrics (CPU, memory, event loop, etc.)
client.collectDefaultMetrics({ prefix: 'alpaca_rl_' });

export const registry = client.register;

// ── Shared business counters ─────────────────────────────────────────

export const httpRequestsTotal = new client.Counter({
  name: 'alpaca_rl_http_requests_total',
  help: 'Total HTTP requests handled',
  labelNames: ['service', 'method', 'route', 'status_code'] as const,
});

export const httpRequestDurationMs = new client.Histogram({
  name: 'alpaca_rl_http_request_duration_ms',
  help: 'HTTP request duration in milliseconds',
  labelNames: ['service', 'method', 'route'] as const,
  buckets: [5, 10, 25, 50, 100, 250, 500, 1000, 2500],
});

export const ordersTotal = new client.Counter({
  name: 'alpaca_rl_orders_total',
  help: 'Total orders submitted',
  labelNames: ['symbol', 'side', 'status'] as const,
});

export const inferLatencyMs = new client.Histogram({
  name: 'alpaca_rl_infer_latency_ms',
  help: 'RL inference latency in milliseconds',
  labelNames: ['symbol', 'action'] as const,
  buckets: [1, 5, 10, 25, 50, 100, 250],
});

export const killSwitchActive = new client.Gauge({
  name: 'alpaca_rl_kill_switch_active',
  help: '1 if the risk kill switch is active, 0 otherwise',
});

export const dailyLossUsd = new client.Gauge({
  name: 'alpaca_rl_daily_loss_usd',
  help: 'Cumulative realised daily loss in USD',
});

export const natsMessagesConsumed = new client.Counter({
  name: 'alpaca_rl_nats_messages_consumed_total',
  help: 'Total NATS messages consumed',
  labelNames: ['stream', 'subject'] as const,
});

export const rlTrainingEpisodes = new client.Counter({
  name: 'alpaca_rl_training_episodes_total',
  help: 'Total RL training episodes completed',
  labelNames: ['run_id', 'symbol'] as const,
});

// ── Strategy-runner business metrics ─────────────────────────────────

export const runnerTicksTotal = new client.Counter({
  name: 'alpaca_rl_runner_ticks_total',
  help: 'Total scheduler ticks',
  labelNames: ['outcome'] as const, // success | skipped_kill_switch | skipped_risk_unavailable | skipped_overlap | error
});

export const runnerTickDurationMs = new client.Histogram({
  name: 'alpaca_rl_runner_tick_duration_ms',
  help: 'Scheduler tick duration in milliseconds',
  buckets: [50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000],
});

export const runnerSignalsTotal = new client.Counter({
  name: 'alpaca_rl_runner_signals_total',
  help: 'Total inference signals received',
  labelNames: ['symbol', 'action'] as const, // action: SHORT | HOLD | LONG
});

export const runnerOrdersSubmittedTotal = new client.Counter({
  name: 'alpaca_rl_runner_orders_submitted_total',
  help: 'Total orders submitted by the runner',
  labelNames: ['symbol', 'side', 'outcome'] as const, // outcome: success | risk_blocked | order_failed | downstream_error
});

export const runnerEquityUsd = new client.Gauge({
  name: 'alpaca_rl_runner_equity_usd',
  help: 'Most recent equity used for sizing (USD)',
});
