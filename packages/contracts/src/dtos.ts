import { z } from 'zod';

// ─────────────────────────────────────────
// Auth DTOs
// ─────────────────────────────────────────
export const LoginRequestSchema = z.object({
  apiKey: z.string().min(1),
  apiSecret: z.string().min(1),
});
export type LoginRequest = z.infer<typeof LoginRequestSchema>;

export const LoginResponseSchema = z.object({
  accessToken: z.string(),
  expiresIn: z.number(),
});
export type LoginResponse = z.infer<typeof LoginResponseSchema>;

// ─────────────────────────────────────────
// Backfill DTOs
// ─────────────────────────────────────────
export const BackfillRequestSchema = z.object({
  symbols: z.array(z.string()).min(1),
  startDate: z.string().date(),
  endDate: z.string().date(),
  timeframe: z.enum(['1m', '1d']),
});
export type BackfillRequest = z.infer<typeof BackfillRequestSchema>;

export const BackfillResponseSchema = z.object({
  jobId: z.string(),
  status: z.string(),
  symbols: z.array(z.string()),
  message: z.string(),
});
export type BackfillResponse = z.infer<typeof BackfillResponseSchema>;

// ─────────────────────────────────────────
// Order DTOs
// ─────────────────────────────────────────
export const SubmitOrderRequestSchema = z.object({
  symbol: z.string(),
  side: z.enum(['buy', 'sell']),
  qty: z.number().positive().optional(),
  notional: z.number().positive().optional(),
  orderType: z.enum(['market', 'limit']).default('limit'),
  limitPrice: z.number().positive().optional(),
  timeInForce: z.enum(['day', 'gtc', 'ioc', 'fok']).default('day'),
  idempotencyKey: z.string(),
  traceId: z.string().optional(),
}).refine((d) => d.qty !== undefined || d.notional !== undefined, {
  message: 'Either qty or notional must be provided',
});
export type SubmitOrderRequest = z.infer<typeof SubmitOrderRequestSchema>;

export const OrderResponseSchema = z.object({
  id: z.string(),
  idempotencyKey: z.string(),
  alpacaOrderId: z.string().optional(),
  symbol: z.string(),
  side: z.string(),
  qty: z.number(),
  status: z.string(),
  createdAt: z.string(),
});
export type OrderResponse = z.infer<typeof OrderResponseSchema>;

// ─────────────────────────────────────────
// Backtest DTOs
// ─────────────────────────────────────────
export const BacktestRequestSchema = z.object({
  name: z.string(),
  symbols: z.array(z.string()).min(1),
  startDate: z.string().date(),
  endDate: z.string().date(),
  initialCapital: z.number().positive().default(100000),
  tradingCostBps: z.number().min(0).default(10),
  timeCostBps: z.number().min(0).default(1),
  datasetId: z.string().uuid().optional(),
  policyId: z.string().uuid().optional(),
  seed: z.number().int().optional(),
});
export type BacktestRequest = z.infer<typeof BacktestRequestSchema>;

export const BacktestEquityCurvePointSchema = z.object({
  time: z.string(),
  nav: z.number(),
  market_nav: z.number(),
  position: z.number().int(),
  strategy_ret: z.number(),
  market_ret: z.number(),
  cost: z.number(),
});
export type BacktestEquityCurvePoint = z.infer<typeof BacktestEquityCurvePointSchema>;

export const BacktestMetricsSchema = z.object({
  initialCapital: z.number(),
  finalNav: z.number(),
  totalReturn: z.number(),
  annualizedReturn: z.number(),
  marketReturn: z.number(),
  annualizedMarketReturn: z.number(),
  alpha: z.number(),
  sharpeRatio: z.number(),
  // null when downside deviation is undefined with a positive mean (no losses)
  sortinoRatio: z.number().nullable(),
  maxDrawdown: z.number(),
  winRate: z.number(),
  // null when there are no losing bars (gross_loss == 0)
  profitFactor: z.number().nullable(),
  totalTrades: z.number().int(),
  totalPositionChanges: z.number().int(),
  totalTradeUnits: z.number().int(),
  tradingDays: z.number().int(),
  equityCurve: z.array(BacktestEquityCurvePointSchema).optional(),
});
export type BacktestMetrics = z.infer<typeof BacktestMetricsSchema>;

// ─────────────────────────────────────────
// RL Training DTOs
// ─────────────────────────────────────────
export const TrainingConfigSchema = z.object({
  name: z.string(),
  symbols: z.array(z.string()).min(1),
  datasetId: z.string().uuid().optional(),
  maxEpisodes: z.number().int().positive().default(1000),
  tradingDays: z.number().int().positive().default(252),
  tradingCostBps: z.number().min(0).default(10),
  timeCostBps: z.number().min(0).default(1),
  gamma: z.number().min(0).max(1).default(0.99),
  learningRate: z.number().positive().default(0.0001),
  batchSize: z.number().int().positive().default(4096),
  replayCapacity: z.number().int().positive().default(1000000),
  architecture: z.array(z.number().int().positive()).default([256, 256]),
  l2Reg: z.number().min(0).default(1e-6),
  tau: z.number().int().positive().default(100),
  epsilonStart: z.number().min(0).max(1).default(1.0),
  epsilonEnd: z.number().min(0).max(1).default(0.01),
  epsilonDecaySteps: z.number().int().positive().default(250),
  epsilonExponentialDecay: z.number().min(0).max(1).default(0.99),
  seed: z.number().int().optional(),
});
export type TrainingConfig = z.infer<typeof TrainingConfigSchema>;

export const TrainingRunResponseSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.string(),
  configHash: z.string(),
  createdAt: z.string(),
  startedAt: z.string().optional(),
  completedAt: z.string().optional(),
  metrics: z.record(z.unknown()).optional(),
  artifactPath: z.string().optional(),
  error: z.string().optional(),
});
export type TrainingRunResponse = z.infer<typeof TrainingRunResponseSchema>;

// ─────────────────────────────────────────
// Policy / inference DTOs
// ─────────────────────────────────────────
export const PromotePolicyRequestSchema = z.object({
  policyId: z.string().uuid(),
  promotedBy: z.string().optional(),
});
export type PromotePolicyRequest = z.infer<typeof PromotePolicyRequestSchema>;

export const InferActionRequestSchema = z.object({
  symbol: z.string(),
  state: z.array(z.number()),
  policyId: z.string().uuid().optional(),
  traceId: z.string().optional(),
});
export type InferActionRequest = z.infer<typeof InferActionRequestSchema>;

export const InferActionResponseSchema = z.object({
  symbol: z.string(),
  action: z.number().int().min(0).max(2),
  actionLabel: z.enum(['SHORT', 'HOLD', 'LONG']),
  qValues: z.array(z.number()).optional(),
  policyId: z.string().uuid(),
  latencyMs: z.number(),
});
export type InferActionResponse = z.infer<typeof InferActionResponseSchema>;

// ─────────────────────────────────────────
// Risk DTOs
// ─────────────────────────────────────────
export const RiskStateResponseSchema = z.object({
  killSwitch: z.boolean(),
  dailyLossUsd: z.number(),
  maxDailyLoss: z.number(),
  reason: z.string().nullable(),
  updatedAt: z.string(),
});
export type RiskStateResponse = z.infer<typeof RiskStateResponseSchema>;

export const HaltRequestSchema = z.object({
  reason: z.string().min(1),
});
export type HaltRequest = z.infer<typeof HaltRequestSchema>;
