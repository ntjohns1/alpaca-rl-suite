import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { AlpacaClient } from './alpacaClient';
import { AlpacaStreamer } from './alpacaStreamer';
import { registry } from '@alpaca-rl/observability';
import { SubmitOrderRequestSchema, HealthResponseSchema } from '@alpaca-rl/contracts';

const config = loadConfig();
const app = Fastify({ logger: true });
const client = new AlpacaClient(config);
const streamer = new AlpacaStreamer(config);

// ── Orders ──────────────────────────────────────────────────────────
app.post('/alpaca/orders', async (req, reply) => {
  const body = SubmitOrderRequestSchema.safeParse(req.body);
  if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
  const order = await client.submitOrder(body.data);
  return reply.status(201).send(order);
});

app.get('/alpaca/orders', async (_req, reply) => {
  const orders = await client.listOrders();
  return reply.send(orders);
});

app.get('/alpaca/orders/:id', async (req: any, reply) => {
  const order = await client.getOrder(req.params.id);
  return reply.send(order);
});

app.delete('/alpaca/orders/:id', async (req: any, reply) => {
  await client.cancelOrder(req.params.id);
  return reply.status(204).send();
});

// ── Positions ───────────────────────────────────────────────────────
app.get('/alpaca/positions', async (_req, reply) => {
  const positions = await client.getPositions();
  return reply.send(positions);
});

app.get('/alpaca/positions/:symbol', async (req: any, reply) => {
  const pos = await client.getPosition(req.params.symbol);
  return reply.send(pos);
});

// ── Account ─────────────────────────────────────────────────────────
app.get('/alpaca/account', async (_req, reply) => {
  const account = await client.getAccount();
  return reply.send(account);
});

// ── Bars (historical) ────────────────────────────────────────────────
app.get('/alpaca/bars/:timeframe/:symbol', async (req: any, reply) => {
  const { timeframe, symbol } = req.params;
  const { start, end } = req.query as { start?: string; end?: string };
  const rawLimit = (req.query as any).limit;
  const limit = rawLimit !== undefined ? (parseInt(rawLimit, 10) || undefined) : undefined;
  const bars = await client.getBars(symbol, timeframe, start, end, limit);
  return reply.send(bars);
});

// ── Health ───────────────────────────────────────────────────────────
const SERVICE_VERSION = process.env.npm_package_version ?? '0.1.0';

app.get('/alpaca/health', async (_req, reply) => {
  const streamingCheckStatus = streamer.streamingDead ? 'error' : 'ok';
  const streamingMessage = !streamer.streamingConfigured
    ? 'disabled'
    : streamer.streamingDead
      ? 'reconnect attempts exhausted'
      : streamer.streamingHealthy
        ? undefined
        : 'reconnecting';

  const body = HealthResponseSchema.parse({
    status: streamer.streamingDead ? 'degraded' : 'ok',
    version: SERVICE_VERSION,
    uptime: process.uptime(),
    checks: {
      streaming: { status: streamingCheckStatus, message: streamingMessage },
    },
  });
  reply.send(body);
});

const SYMBOL_PATTERN = /^[A-Z][A-Z0-9.]{0,7}$/;
// 30 is the Alpaca IEX free-tier concurrent-symbol connection limit; SIP accounts may allow more
const MAX_STREAM_SYMBOLS = 30;

const start = async () => {
  await streamer.connect();

  // Subscribe to real-time bar streaming if symbols are configured
  if (config.STREAM_SYMBOLS) {
    const symbols = config.STREAM_SYMBOLS.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (symbols.length > MAX_STREAM_SYMBOLS) {
      throw new Error(
        `STREAM_SYMBOLS has ${symbols.length} symbols, max is ${MAX_STREAM_SYMBOLS}`,
      );
    }
    const invalid = symbols.filter((s) => !SYMBOL_PATTERN.test(s));
    if (invalid.length > 0) {
      throw new Error(`STREAM_SYMBOLS contains invalid tickers: ${invalid.join(', ')}`);
    }
    if (symbols.length > 0) {
      await streamer.subscribeToDataStream(symbols);
      console.log(`Subscribed to real-time bars for: ${symbols.join(', ')}`);
    }
  }

  await app.listen({ port: config.ALPACA_ADAPTER_PORT, host: '0.0.0.0' });
  console.log(`Alpaca Adapter listening on port ${config.ALPACA_ADAPTER_PORT}`);
};

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

start().catch((err) => { console.error(err); process.exit(1); });
