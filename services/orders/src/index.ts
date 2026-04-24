import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { SubmitOrderRequestSchema } from '@alpaca-rl/contracts';
import { registry } from '@alpaca-rl/observability';
import { OrdersDb } from './ordersDb';
import { OrdersService } from './ordersService';
import { v4 as uuidv4 } from 'uuid';

const config = loadConfig();
const app = Fastify({ logger: true });
const db = new OrdersDb(config);
const svc = new OrdersService(config, db);

app.post('/orders', async (req, reply) => {
  const body = SubmitOrderRequestSchema.safeParse(req.body);
  if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
  const traceId = (req as any).traceId ?? uuidv4();
  const result = await svc.submitOrder({ ...body.data, traceId });
  return reply.status(201).send(result);
});

app.get('/orders', async (_req, reply) => {
  const rows = await db.listOrders();
  return reply.send(rows);
});

app.get('/orders/:id', async (req: any, reply) => {
  const row = await db.getOrder(req.params.id);
  if (!row) return reply.status(404).send({ error: 'Order not found' });
  return reply.send(row);
});

app.delete('/orders/:id', async (req: any, reply) => {
  await svc.cancelOrder(req.params.id);
  return reply.status(204).send();
});

app.get('/orders/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'orders' });
});

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

app.listen({ port: config.ORDERS_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
});
