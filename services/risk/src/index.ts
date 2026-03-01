import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { HaltRequestSchema } from '@alpaca-rl/contracts';
import { registry } from '@alpaca-rl/observability';
import { RiskDb } from './riskDb';

const config = loadConfig();
const app = Fastify({ logger: true });
const db = new RiskDb(config);

// ── State ────────────────────────────────────────────────────────────
app.get('/risk/state', async (_req, reply) => {
  const state = await db.getState();
  return reply.send(state);
});

// ── Kill switch ───────────────────────────────────────────────────────
app.post('/risk/halt', async (req, reply) => {
  const body = HaltRequestSchema.safeParse(req.body);
  if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
  await db.setKillSwitch(true, body.data.reason);
  app.log.warn({ reason: body.data.reason }, 'KILL SWITCH ACTIVATED');
  return reply.send({ killSwitch: true, reason: body.data.reason });
});

app.post('/risk/resume', async (_req, reply) => {
  await db.setKillSwitch(false, null);
  app.log.info('Kill switch cleared');
  return reply.send({ killSwitch: false });
});

// ── Pre-order risk check ──────────────────────────────────────────────
app.post('/risk/check', async (req: any, reply) => {
  const state = await db.getState();

  if (state.kill_switch) {
    return reply.status(403).send({ allowed: false, reason: 'Kill switch active' });
  }

  const { notional = 0, symbol } = req.body ?? {};
  if (Math.abs(notional) > config.MAX_POSITION_SIZE_PCT * (state.portfolio_value ?? 100000)) {
    return reply.status(403).send({
      allowed: false,
      reason: `Order size exceeds max position size (${config.MAX_POSITION_SIZE_PCT * 100}%)`,
    });
  }

  if (state.daily_loss_usd >= state.max_daily_loss) {
    return reply.status(403).send({
      allowed: false,
      reason: `Daily loss limit reached ($${state.daily_loss_usd} / $${state.max_daily_loss})`,
    });
  }

  return reply.send({ allowed: true, symbol });
});

// ── Update daily P&L ─────────────────────────────────────────────────
app.post('/risk/daily-pl', async (req: any, reply) => {
  const { dailyLoss } = req.body ?? {};
  await db.updateDailyLoss(dailyLoss ?? 0);
  return reply.send({ ok: true });
});

app.get('/risk/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'risk' });
});

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

app.listen({ port: config.RISK_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
});
