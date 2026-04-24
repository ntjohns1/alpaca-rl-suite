import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { BackfillRequestSchema } from '@alpaca-rl/contracts';
import { registry } from '@alpaca-rl/observability';
import { BackfillJob } from './backfillJob';
import { DbClient } from './dbClient';
import { NatsBarConsumer } from './natsConsumer';
import { v4 as uuidv4 } from 'uuid';

const config = loadConfig();
const app = Fastify({ logger: true });
const db = new DbClient(config);

app.post('/market/backfill', async (req, reply) => {
  const body = BackfillRequestSchema.safeParse(req.body);
  if (!body.success) return reply.status(400).send({ error: body.error.flatten() });

  const jobId = uuidv4();
  const job = new BackfillJob(config, db);

  // Run async, don't block response
  job.run(body.data).catch((err: Error) =>
    app.log.error({ err, jobId }, 'Backfill job failed'),
  );

  return reply.status(202).send({
    jobId,
    status: 'accepted',
    symbols: body.data.symbols,
    message: `Backfill started for ${body.data.symbols.length} symbol(s)`,
  });
});

app.get('/market/bars/:symbol', async (req: any, reply) => {
  const { symbol } = req.params;
  const { timeframe = '1d', start, end, limit = 500 } = req.query as any;
  const table = timeframe === '1m' ? 'bar_1m' : 'bar_1d';
  const rows = await db.queryBars(table, symbol, start, end, Number(limit));
  return reply.send(rows);
});

app.get('/market/symbols', async (_req, reply) => {
  const rows = await db.querySymbols();
  return reply.send(rows);
});

app.get('/market/availability', async (req: any, reply) => {
  const { symbols, start, end, timeframe = '1d' } = req.query as any;
  if (!symbols || !start || !end) {
    return reply.status(400).send({ error: 'symbols, start, and end are required' });
  }
  const table = timeframe === '1m' ? 'bar_1m' : 'bar_1d';
  const symbolList: string[] = String(symbols).split(',').map((s: string) => s.trim());
  const results = await Promise.all(
    symbolList.map(async (symbol: string) => {
      const available = await db.queryBarCount(table, symbol, start, end);
      return { symbol, available };
    })
  );
  return reply.send(results);
});

app.get('/market/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'market-ingest' });
});

const natsConsumer = new NatsBarConsumer(config, db);

app.listen({ port: config.MARKET_INGEST_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
  console.log(`Market Ingest listening on port ${config.MARKET_INGEST_PORT}`);
  natsConsumer.connect()
    .then(() => natsConsumer.startConsuming())
    .catch((e) => app.log.error({ err: e }, 'NATS consumer failed to start'));
});

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

process.on('SIGTERM', async () => {
  await natsConsumer.stop();
  process.exit(0);
});
