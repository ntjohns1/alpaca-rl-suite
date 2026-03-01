import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { AlpacaClient } from './alpacaClient';
import { AlpacaStreamer } from './alpacaStreamer';
import { registry } from '@alpaca-rl/observability';
import { SubmitOrderRequestSchema } from '@alpaca-rl/contracts';

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
  const { start, end, limit } = req.query as any;
  const bars = await client.getBars(symbol, timeframe, start, end, limit);
  return reply.send(bars);
});

// ── Health ───────────────────────────────────────────────────────────
app.get('/alpaca/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'alpaca-adapter', mode: config.TRADING_MODE });
});

const start = async () => {
  await streamer.connect();
  await app.listen({ port: config.ALPACA_ADAPTER_PORT, host: '0.0.0.0' });
  console.log(`Alpaca Adapter listening on port ${config.ALPACA_ADAPTER_PORT}`);
};

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

start().catch((err) => { console.error(err); process.exit(1); });
