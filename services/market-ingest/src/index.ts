import './tracing';
import { shutdown as shutdownTracing } from './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { BackfillRequestSchema } from '@alpaca-rl/contracts';
import { registry } from '@alpaca-rl/observability';
import { createRequireAuth } from '@alpaca-rl/auth-middleware';
import { BackfillJob } from './backfillJob';
import { DbClient } from './dbClient';
import { NatsBarConsumer } from './natsConsumer';
import { v4 as uuidv4 } from 'uuid';

const config = loadConfig();
const app = Fastify({ logger: true });
const db = new DbClient(config);

const auth = createRequireAuth(config.JWT_SECRET, 'market-ingest');

// Tracks running backfill promises so SIGTERM can await them before exiting.
const inflight = new Set<Promise<void>>();

app.post('/market/backfill', { preHandler: auth('market:write') }, async (req, reply) => {
  const body = BackfillRequestSchema.safeParse(req.body);
  if (!body.success) return reply.status(400).send({ error: body.error.flatten() });

  const jobId = uuidv4();
  const job = new BackfillJob(config, db, app.log);

  const p = job.run(body.data).catch((err: Error) =>
    app.log.error({ err, jobId }, 'Backfill job failed'),
  );
  inflight.add(p);
  p.finally(() => inflight.delete(p));

  return reply.status(202).send({
    jobId,
    status: 'accepted',
    symbols: body.data.symbols,
    message: `Backfill started for ${body.data.symbols.length} symbol(s)`,
  });
});

app.get<{
  Params: { symbol: string };
  Querystring: { timeframe?: string; start?: string; end?: string; limit?: string };
}>('/market/bars/:symbol', async (req, reply) => {
  const { symbol } = req.params;
  const { timeframe = '1d', start, end, limit = '500' } = req.query;
  const table = timeframe === '1m' ? 'bar_1m' : 'bar_1d';
  const safeLimit = Math.min(Math.max(parseInt(limit, 10) || 500, 1), 5000);
  const rows = await db.queryBars(table, symbol, start, end, safeLimit);
  return reply.send(rows);
});

app.get('/market/symbols', async (_req, reply) => {
  const rows = await db.querySymbols();
  return reply.send(rows);
});

app.get<{
  Querystring: { symbols?: string; start?: string; end?: string; timeframe?: string };
}>('/market/availability', async (req, reply) => {
  const { symbols, start, end, timeframe = '1d' } = req.query;
  if (!symbols || !start || !end) {
    return reply.status(400).send({ error: 'symbols, start, and end are required' });
  }
  const table = timeframe === '1m' ? 'bar_1m' : 'bar_1d';
  const symbolList = symbols.split(',').map((s) => s.trim());
  const results = await Promise.all(
    symbolList.map(async (symbol) => {
      const available = await db.queryBarCount(table, symbol, start, end);
      return { symbol, available };
    })
  );
  return reply.send(results);
});

app.get('/market/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'market-ingest' });
});

// /metrics is expected to be reachable only within the cluster mesh.
app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

const natsConsumer = new NatsBarConsumer(config, db, app.log);

app.listen({ port: config.MARKET_INGEST_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
  app.log.info({ port: config.MARKET_INGEST_PORT }, 'Market Ingest listening');
  natsConsumer.connect()
    .then(() => natsConsumer.startConsuming())
    .catch((e) => app.log.error({ err: e }, 'NATS consumer failed to start'));
});

// Kubernetes sends SIGTERM before SIGKILL (default 30s gap).
// We budget 20s for in-flight backfills to finish or time out inside fetchBars,
// leaving 10s for NATS drain and tracing flush before SIGKILL would fire.
const DRAIN_TIMEOUT_MS = 20_000;

process.on('SIGTERM', async () => {
  app.log.info('SIGTERM received, shutting down');

  if (inflight.size > 0) {
    app.log.warn({ count: inflight.size }, 'SIGTERM: waiting for in-flight backfill jobs');
    const deadline = new Promise<void>((resolve) =>
      setTimeout(() => { app.log.error('SIGTERM: backfill drain timed out'); resolve(); }, DRAIN_TIMEOUT_MS),
    );
    await Promise.race([Promise.allSettled([...inflight]), deadline]);
    app.log.info('SIGTERM: backfill drain complete');
  }

  await natsConsumer.stop();
  await shutdownTracing();
  process.exit(0);
});
