import Fastify, { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import jwt from 'jsonwebtoken';
import { Config, loadConfig } from '@alpaca-rl/config';
import {
  HaltRequestSchema,
  RiskCheckRequestSchema,
  PortfolioValueRequestSchema,
  DailyPLRequestSchema,
} from '@alpaca-rl/contracts';
import { registry } from '@alpaca-rl/observability';
import { RiskDb } from './riskDb';

// Verifies a Bearer JWT, requires `aud` to include 'risk', and (when a scope
// is specified) requires the token's `scope` claim to contain it.
function requireAuth(config: Config, scope?: string) {
  return async (req: FastifyRequest, reply: FastifyReply) => {
    const auth = req.headers.authorization;
    if (!auth?.startsWith('Bearer ')) {
      req.log.warn({ ip: req.ip, route: req.url }, 'auth: missing bearer token');
      return reply.status(401).send({ error: 'missing bearer token' });
    }
    let payload: any;
    try {
      payload = jwt.verify(auth.slice(7), config.JWT_SECRET, {
        algorithms: ['HS256'],
        audience: 'risk',
      });
    } catch (err: any) {
      req.log.warn(
        { ip: req.ip, route: req.url, reason: err?.name ?? 'unknown' },
        'auth: token verification failed',
      );
      return reply.status(401).send({ error: 'invalid token' });
    }
    if (scope) {
      const claim = payload?.scope;
      const scopes = typeof claim === 'string' ? claim.split(/\s+/).filter(Boolean) : [];
      if (!scopes.includes(scope)) {
        req.log.warn(
          { ip: req.ip, route: req.url, sub: payload?.sub, required: scope },
          'auth: missing required scope',
        );
        return reply.status(403).send({ error: 'insufficient scope', required: scope });
      }
    }
    (req as any).authSub = payload?.sub;
  };
}

export function createApp(config: Config = loadConfig()): FastifyInstance {
  const app = Fastify({ logger: true });
  const db = new RiskDb(config);

  const auth = (scope?: string) => requireAuth(config, scope);

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
    app.log.warn({ reason: body.data.reason }, 'KILL SWITCH ACTIVATED');
    return reply.send({ killSwitch: true, reason: body.data.reason });
  });

  app.post('/risk/resume', { preHandler: auth('risk:write') }, async (_req, reply) => {
    await db.setKillSwitch(false, null);
    app.log.info('Kill switch cleared');
    return reply.send({ killSwitch: false });
  });

  // ── Pre-order risk check ──────────────────────────────────────────────
  app.post('/risk/check', async (req, reply) => {
    const body = RiskCheckRequestSchema.safeParse(req.body);
    if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
    const { notional, symbol } = body.data;

    const state = await db.getState();

    if (state.kill_switch) {
      return reply.status(403).send({ allowed: false, reason: 'kill_switch_active' });
    }

    const portfolioValue = state.portfolio_value == null ? null : Number(state.portfolio_value);
    if (portfolioValue == null) {
      return reply.status(503).send({
        allowed: false,
        reason: 'portfolio_unsynced',
      });
    }

    // Reject if the portfolio value was last synced longer ago than the
    // configured staleness threshold. A stale balance can cause risk to
    // size positions against morning equity while the account has already
    // moved significantly intraday.
    const updatedAt = state.portfolio_value_updated_at
      ? new Date(state.portfolio_value_updated_at).getTime()
      : null;
    if (updatedAt == null || Date.now() - updatedAt > config.MAX_PORTFOLIO_STALENESS_S * 1000) {
      return reply.status(503).send({
        allowed: false,
        reason: 'portfolio_stale',
      });
    }

    if (Math.abs(notional) > config.MAX_POSITION_SIZE_PCT * portfolioValue) {
      return reply.status(403).send({
        allowed: false,
        reason: `Order size exceeds max position size (${config.MAX_POSITION_SIZE_PCT * 100}%)`,
      });
    }

    if (Number(state.daily_loss_usd) >= Number(state.max_daily_loss)) {
      return reply.status(403).send({
        allowed: false,
        reason: `Daily loss limit reached ($${state.daily_loss_usd} / $${state.max_daily_loss})`,
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
    const prior = await db.getState();
    await db.resetDailyLoss();
    app.log.warn(
      { sub: (req as any).authSub, prior: prior.daily_loss_usd },
      'Daily loss reset to 0',
    );
    return reply.send({ ok: true });
  });

  // ── Portfolio value sync ─────────────────────────────────────────────
  app.post('/risk/portfolio', { preHandler: auth('risk:write') }, async (req, reply) => {
    const body = PortfolioValueRequestSchema.safeParse(req.body);
    if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
    const prior = await db.getState();
    await db.updatePortfolioValue(body.data.portfolioValue);
    app.log.info(
      {
        sub: (req as any).authSub,
        prior: prior.portfolio_value,
        next: body.data.portfolioValue,
      },
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
