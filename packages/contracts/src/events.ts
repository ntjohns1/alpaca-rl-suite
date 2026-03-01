import { z } from 'zod';

// ─────────────────────────────────────────
// NATS subject constants
// ─────────────────────────────────────────
export const SUBJECTS = {
  MARKET_BAR_1M: 'market.bar.1m',
  MARKET_BAR_1D: 'market.bar.1d',
  ORDER_SUBMITTED: 'orders.submitted',
  ORDER_FILLED: 'orders.filled',
  ORDER_CANCELLED: 'orders.cancelled',
  ORDER_FAILED: 'orders.failed',
  POSITION_UPDATED: 'portfolio.position.updated',
  ACCOUNT_UPDATED: 'portfolio.account.updated',
  TRAINING_STARTED: 'rl.training.started',
  TRAINING_COMPLETED: 'rl.training.completed',
  TRAINING_FAILED: 'rl.training.failed',
  INFER_REQUEST: 'rl.infer.request',
  INFER_RESPONSE: 'rl.infer.response',
  RISK_HALT: 'risk.halt',
  RISK_RESUME: 'risk.resume',
} as const;

// ─────────────────────────────────────────
// Market bar event
// ─────────────────────────────────────────
export const BarEventSchema = z.object({
  traceId: z.string(),
  symbol: z.string(),
  time: z.string().datetime(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().int(),
  vwap: z.number().optional(),
  tradeCount: z.number().int().optional(),
  timeframe: z.enum(['1m', '1d']),
});
export type BarEvent = z.infer<typeof BarEventSchema>;

// ─────────────────────────────────────────
// Order events
// ─────────────────────────────────────────
export const OrderEventSchema = z.object({
  traceId: z.string(),
  idempotencyKey: z.string(),
  alpacaOrderId: z.string().optional(),
  symbol: z.string(),
  side: z.enum(['buy', 'sell']),
  qty: z.number(),
  notional: z.number().optional(),
  orderType: z.enum(['market', 'limit', 'stop', 'stop_limit']),
  limitPrice: z.number().optional(),
  status: z.enum(['pending', 'accepted', 'partially_filled', 'filled', 'cancelled', 'rejected', 'failed']),
  filledQty: z.number().optional(),
  filledAvgPrice: z.number().optional(),
  commission: z.number().optional(),
  timestamp: z.string().datetime(),
});
export type OrderEvent = z.infer<typeof OrderEventSchema>;

// ─────────────────────────────────────────
// Portfolio events
// ─────────────────────────────────────────
export const PositionEventSchema = z.object({
  traceId: z.string(),
  symbol: z.string(),
  qty: z.number(),
  avgEntryPrice: z.number(),
  marketValue: z.number().optional(),
  unrealizedPl: z.number().optional(),
  currentPrice: z.number().optional(),
  timestamp: z.string().datetime(),
});
export type PositionEvent = z.infer<typeof PositionEventSchema>;

export const AccountEventSchema = z.object({
  traceId: z.string(),
  equity: z.number(),
  cash: z.number(),
  buyingPower: z.number(),
  portfolioValue: z.number(),
  dailyPl: z.number().optional(),
  timestamp: z.string().datetime(),
});
export type AccountEvent = z.infer<typeof AccountEventSchema>;

// ─────────────────────────────────────────
// RL events
// ─────────────────────────────────────────
export const TrainingJobEventSchema = z.object({
  traceId: z.string(),
  runId: z.string().uuid(),
  name: z.string(),
  configHash: z.string(),
  datasetId: z.string().uuid().optional(),
  timestamp: z.string().datetime(),
});
export type TrainingJobEvent = z.infer<typeof TrainingJobEventSchema>;

export const TrainingCompletedEventSchema = TrainingJobEventSchema.extend({
  artifactPath: z.string(),
  metrics: z.object({
    finalNavMean: z.number(),
    winRate: z.number(),
    sharpeRatio: z.number().optional(),
    maxDrawdown: z.number().optional(),
    totalEpisodes: z.number().int(),
  }),
});
export type TrainingCompletedEvent = z.infer<typeof TrainingCompletedEventSchema>;

export const InferRequestSchema = z.object({
  traceId: z.string(),
  symbol: z.string(),
  state: z.array(z.number()),
  policyId: z.string().uuid().optional(),
});
export type InferRequest = z.infer<typeof InferRequestSchema>;

export const InferResponseSchema = z.object({
  traceId: z.string(),
  symbol: z.string(),
  action: z.number().int().min(0).max(2), // 0=SHORT, 1=HOLD, 2=LONG
  qValues: z.array(z.number()).optional(),
  policyId: z.string().uuid(),
  latencyMs: z.number(),
});
export type InferResponse = z.infer<typeof InferResponseSchema>;

// ─────────────────────────────────────────
// Risk events
// ─────────────────────────────────────────
export const RiskHaltEventSchema = z.object({
  traceId: z.string(),
  reason: z.string(),
  triggeredBy: z.string(),
  timestamp: z.string().datetime(),
});
export type RiskHaltEvent = z.infer<typeof RiskHaltEventSchema>;
