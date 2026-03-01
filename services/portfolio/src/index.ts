import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { PortfolioDb } from './portfolioDb';
import { registry } from '@alpaca-rl/observability';
import { PortfolioService } from './portfolioService';
import { SyncCron } from './syncCron';

const config = loadConfig();
const app = Fastify({ logger: true });
const db = new PortfolioDb(config);
const svc = new PortfolioService(config, db);

app.get('/portfolio/positions', async (_req, reply) => {
  const positions = await db.getLatestPositions();
  return reply.send(positions);
});

app.get('/portfolio/account', async (_req, reply) => {
  const account = await db.getLatestAccount();
  return reply.send(account);
});

app.post('/portfolio/sync', async (_req, reply) => {
  await svc.syncFromBroker();
  return reply.send({ ok: true });
});

app.get('/portfolio/history', async (req: any, reply) => {
  const { start, end, limit = 500 } = req.query ?? {};
  const rows = await db.getAccountHistory(start, end, Number(limit));
  return reply.send(rows);
});

app.get('/portfolio/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'portfolio' });
});

const cron = new SyncCron(config);

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

app.listen({ port: config.PORTFOLIO_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
  const syncIntervalMs = parseInt(process.env['PORTFOLIO_SYNC_INTERVAL_MS'] ?? '60000', 10);
  cron.start(syncIntervalMs);
});

process.on('SIGTERM', () => { cron.stop(); process.exit(0); });
