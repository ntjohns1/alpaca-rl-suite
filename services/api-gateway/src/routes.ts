import { FastifyInstance } from 'fastify';
import { getConfig } from '@alpaca-rl/config';

function getUpstreamConfig(): Record<string, string> {
  const config = getConfig();
  return {
    '/auth':            config.AUTH_SERVICE_URL,
    '/market':          config.MARKET_INGEST_URL,
    '/portfolio':       config.PORTFOLIO_URL,
    '/orders':          config.ORDERS_URL,
    '/risk':            config.RISK_URL,
    '/backtest':        config.BACKTEST_URL,
    '/features':        config.FEATURE_BUILDER_URL,
    '/rl/train':        `http://localhost:${config.RL_TRAIN_PORT}`,
    '/rl/infer':        config.RL_INFER_URL,
  };
}

async function proxyTo(upstream: string, req: any, reply: any) {
  const url = `${upstream}${req.url}`;
  const headers: Record<string, string> = {
    'content-type': req.headers['content-type'] ?? 'application/json',
    'x-trace-id': req.traceId,
    ...(req.headers.authorization ? { authorization: req.headers.authorization } : {}),
  };

  const options: RequestInit = {
    method: req.method,
    headers,
    ...(req.method !== 'GET' && req.method !== 'HEAD' && req.body
      ? { body: JSON.stringify(req.body) }
      : {}),
  };

  const res = await fetch(url, options);
  const text = await res.text();
  reply.status(res.status);
  res.headers.forEach((val, key) => {
    if (!['transfer-encoding', 'connection'].includes(key)) {
      reply.header(key, val);
    }
  });
  reply.send(text);
}

export function registerRoutes(app: FastifyInstance) {
  app.get('/health', async (_req, reply) => {
    reply.send({ status: 'ok', service: 'api-gateway' });
  });

  const UPSTREAM = getUpstreamConfig();
  for (const [prefix, upstream] of Object.entries(UPSTREAM)) {
    app.all(`${prefix}`, async (req, reply) => proxyTo(upstream, req, reply));
    app.all(`${prefix}/*`, async (req, reply) => proxyTo(upstream, req, reply));
  }
}
