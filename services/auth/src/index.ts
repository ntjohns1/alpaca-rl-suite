import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { LoginRequestSchema } from '@alpaca-rl/contracts';
import jwt from 'jsonwebtoken';
import { registry } from '@alpaca-rl/observability';

const config = loadConfig();
const app = Fastify({ logger: true });

app.post('/auth/login', async (req, reply) => {
  const body = LoginRequestSchema.safeParse(req.body);
  if (!body.success) {
    return reply.status(400).send({ error: 'Invalid credentials format' });
  }

  if (
    body.data.apiKey !== config.ALPACA_API_KEY ||
    body.data.apiSecret !== config.ALPACA_API_SECRET
  ) {
    return reply.status(401).send({ error: 'Invalid credentials' });
  }

  const token = jwt.sign(
    { sub: body.data.apiKey, iat: Math.floor(Date.now() / 1000) },
    config.JWT_SECRET,
    { expiresIn: config.JWT_EXPIRES_IN } as any,
  );

  return reply.send({ accessToken: token, expiresIn: 86400 });
});

app.get('/auth/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'auth' });
});

app.get('/auth/verify', async (req, reply) => {
  const auth = req.headers.authorization;
  if (!auth?.startsWith('Bearer ')) {
    return reply.status(401).send({ error: 'Missing token' });
  }
  try {
    const decoded = jwt.verify(auth.slice(7), config.JWT_SECRET);
    return reply.send({ valid: true, payload: decoded });
  } catch {
    return reply.status(401).send({ valid: false, error: 'Invalid token' });
  }
});

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

app.listen({ port: config.AUTH_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
});
