import './tracing';
import Fastify, { FastifyReply, FastifyRequest } from 'fastify';
import jwt from 'jsonwebtoken';
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

// Verifies a Bearer JWT, requires `aud` to include 'orders', and (when a
// scope is specified) requires the token's `scope` claim to contain it.
//
// Notes:
// - The shared HMAC secret means a token issued by `auth` can be used by any
//   service that knows JWT_SECRET. The `aud` and `scope` checks narrow this:
//   a strategy-runner-only token (no `orders` aud or no `orders:*` scope)
//   cannot place orders here. Migrating to asymmetric (RS256/JWKS) keys is
//   tracked separately and does not block this fix.
// - On rejection we log the *type* of failure and the source IP at warn
//   level, never the token itself.
function requireAuth(scope?: string) {
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
        audience: 'orders',
      });
    } catch (err: any) {
      req.log.warn(
        { ip: req.ip, route: req.url, reason: err?.name ?? 'unknown' },
        'auth: token verification failed',
      );
      return reply.status(401).send({ error: 'invalid token' });
    }
    if (scope) {
      // RFC 8693 / OAuth 2.0 defines `scope` as a space-delimited string.
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

app.get('/orders/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'orders' });
});

app.post('/orders', { preHandler: requireAuth('orders:write') }, async (req, reply) => {
  const body = SubmitOrderRequestSchema.safeParse(req.body);
  if (!body.success) return reply.status(400).send({ error: body.error.flatten() });
  const traceId = (req as any).traceId ?? uuidv4();
  const result = await svc.submitOrder({ ...body.data, traceId });
  app.log.info(
    { sub: (req as any).authSub, idempotencyKey: body.data.idempotencyKey },
    'order submitted',
  );
  return reply.status(201).send(result);
});

app.get('/orders', { preHandler: requireAuth('orders:read') }, async (_req, reply) => {
  const rows = await db.listOrders();
  return reply.send(rows);
});

app.get('/orders/:id', { preHandler: requireAuth('orders:read') }, async (req: any, reply) => {
  const row = await db.getOrder(req.params.id);
  if (!row) return reply.status(404).send({ error: 'Order not found' });
  return reply.send(row);
});

app.delete('/orders/:id', { preHandler: requireAuth('orders:write') }, async (req: any, reply) => {
  await svc.cancelOrder(req.params.id);
  req.log.info({ sub: (req as any).authSub, id: req.params.id }, 'order cancelled');
  return reply.status(204).send();
});

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

app.listen({ port: config.ORDERS_PORT, host: '0.0.0.0' }, (err) => {
  if (err) {
    app.log.error(err);
    process.exit(1);
  }
});
