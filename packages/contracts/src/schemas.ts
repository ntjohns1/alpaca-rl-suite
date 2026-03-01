import { z } from 'zod';

// ─────────────────────────────────────────
// Common
// ─────────────────────────────────────────
export const PaginationSchema = z.object({
  page: z.coerce.number().int().positive().default(1),
  limit: z.coerce.number().int().positive().max(500).default(50),
});
export type Pagination = z.infer<typeof PaginationSchema>;

export const HealthResponseSchema = z.object({
  status: z.enum(['ok', 'degraded', 'error']),
  version: z.string(),
  uptime: z.number(),
  checks: z.record(z.object({
    status: z.enum(['ok', 'error']),
    message: z.string().optional(),
  })),
});
export type HealthResponse = z.infer<typeof HealthResponseSchema>;

export const ErrorResponseSchema = z.object({
  error: z.string(),
  code: z.string().optional(),
  traceId: z.string().optional(),
  details: z.unknown().optional(),
});
export type ErrorResponse = z.infer<typeof ErrorResponseSchema>;

// ─────────────────────────────────────────
// Bar query schema
// ─────────────────────────────────────────
export const BarQuerySchema = z.object({
  symbol: z.string(),
  startDate: z.string().datetime().optional(),
  endDate: z.string().datetime().optional(),
  timeframe: z.enum(['1m', '1d']).default('1d'),
  limit: z.coerce.number().int().positive().max(10000).default(500),
});
export type BarQuery = z.infer<typeof BarQuerySchema>;

// ─────────────────────────────────────────
// Action labels
// ─────────────────────────────────────────
export const ACTION_LABELS = ['SHORT', 'HOLD', 'LONG'] as const;
export type ActionLabel = typeof ACTION_LABELS[number];

export function actionToLabel(action: number): ActionLabel {
  return ACTION_LABELS[action] ?? 'HOLD';
}
