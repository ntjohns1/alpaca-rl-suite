import Fastify, { FastifyInstance } from 'fastify';
import { Config, loadConfig } from '@alpaca-rl/config';
import {
  HaltRequestSchema,
  RiskCheckRequestSchema,
  PortfolioValueRequestSchema,
  DailyPLRequestSchema,
} from '@alpaca-rl/contracts';
import { registry } from '@alpaca-rl/observability';
import { createRequireAuth } from '@alpaca-rl/auth-middleware';
import { RiskDb } from './riskDb.js';

// Stable reason codes returned in every non-200 response. The `message` field
// carries the human-readable detail; only `reason` should be used for branching.
const REASON = {
  KILL_SWITCH_ACTIVE:    'kill_switch_active',
  PORTFOLIO_UNSYNCED:    'portfolio_unsynced',
  PORTFOLIO_STALE:       'portfolio_stale',
  MAX_POSITION_EXCEEDED: 'max_position_exceeded',
  DAILY_LOSS_EXCEEDED:   'daily_loss_exceeded',
} as const;

export function createApp(
  config: Config = loadConfig(),
  db: RiskDb = new RiskDb(config),
): FastifyInstance {
  const app = Fastify({ logger: true });
  const auth = createRequireAuth(config.JWT_SECRET, 'risk');

  // ── State ────────────────────────────────────────────────────────────
  app.get('/risk/state', async (_req, reply) => {
    const state = await db.getState();
    return reply.send(state);
  });

  // ── Kill switch ───────────────────────────────────────────────────────
  app.post('/risk/halt', { preHandler: auth('risk:write') }, async (req, reply) => {
    const body = HaltRequestSchema.safeParse(req.body);
    if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
    await db.setKillSwitch(true, body.data.reason);
    app.log.warn({ reason: body.data.reason, sub: req.authSub }, 'KILL SWITCH ACTIVATED');
    return reply.send({ killSwitch: true, reason: body.data.reason });
  });

  app.post('/risk/resume', { preHandler: auth('risk:write') }, async (req, reply) => {
    await db.setKillSwitch(false, null);
    app.log.info({ sub: req.authSub }, 'Kill switch cleared');
    return reply.send({ killSwitch: false });
  });

  // ── Pre-order risk check ──────────────────────────────────────────────
  app.post('/risk/check', async (req, reply) => {
    const body = RiskCheckRequestSchema.safeParse(req.body);
    if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
    const { notional, symbol } = body.data;

    const state = await db.getState();

    if (state.kill_switch) {
      return reply.status(403).send({
        allowed: false,
        reason: REASON.KILL_SWITCH_ACTIVE,
      });
    }

    const portfolioValue = state.portfolio_value == null ? null : Number(state.portfolio_value);
    if (portfolioValue == null) {
      return reply.status(503).send({
        allowed: false,
        reason: REASON.PORTFOLIO_UNSYNCED,
        message: 'Portfolio value not synced — cannot evaluate position size',
      });
    }

    // Reject if the portfolio_value was last synced longer ago than the
    // configured staleness threshold. A stale balance can cause risk to size
    // positions against morning equity while the account has moved intraday.
    const updatedAt = state.portfolio_value_updated_at
      ? new Date(state.portfolio_value_updated_at).getTime()
      : null;
    if (updatedAt == null || Date.now() - updatedAt > config.MAX_PORTFOLIO_STALENESS_S * 1000) {
      return reply.status(503).send({
        allowed: false,
        reason: REASON.PORTFOLIO_STALE,
        message: `Portfolio value is stale (threshold: ${config.MAX_PORTFOLIO_STALENESS_S}s)`,
      });
    }

    if (Math.abs(notional) > config.MAX_POSITION_SIZE_PCT * portfolioValue) {
      return reply.status(403).send({
        allowed: false,
        reason: REASON.MAX_POSITION_EXCEEDED,
        message: `Order size exceeds max position size (${config.MAX_POSITION_SIZE_PCT * 100}%)`,
      });
    }

    if (Number(state.daily_loss_usd) >= Number(state.max_daily_loss)) {
      return reply.status(403).send({
        allowed: false,
        reason: REASON.DAILY_LOSS_EXCEEDED,
        message: `Daily loss limit reached ($${state.daily_loss_usd} / $${state.max_daily_loss})`,
      });
    }

    return reply.send({ allowed: true, symbol });
  });

  // ── Update daily P&L ─────────────────────────────────────────────────
  app.post('/risk/daily-pl', { preHandler: auth('risk:write') }, async (req, reply) => {
    const body = DailyPLRequestSchema.safeParse(req.body);
    if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
    await db.updateDailyLoss(body.data.dailyLoss);
    return reply.send({ ok: true });
  });

  // ── Reset daily P&L ──────────────────────────────────────────────────
  app.post('/risk/reset-daily-loss', { preHandler: auth('risk:write') }, async (req, reply) => {
    const { prior } = await db.resetDailyLoss();
    app.log.warn({ sub: req.authSub, prior }, 'Daily loss reset to 0');
    return reply.send({ ok: true });
  });

  // ── Portfolio value sync ─────────────────────────────────────────────
  app.post('/risk/portfolio', { preHandler: auth('risk:write') }, async (req, reply) => {
    const body = PortfolioValueRequestSchema.safeParse(req.body);
    if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
    const { prior } = await db.updatePortfolioValue(body.data.portfolioValue);
    app.log.info(
      { sub: req.authSub, prior, next: body.data.portfolioValue },
      'Portfolio value updated',
    );
    return reply.send({ ok: true, portfolioValue: body.data.portfolioValue });
  });

  app.get('/risk/health', async (_req, reply) => {
    reply.send({ status: 'ok', service: 'risk' });
  });

  app.get('/metrics', async (_req, reply) => {
    reply.header('Content-Type', registry.contentType);
    return reply.send(await registry.metrics());
  });

  return app;
}
