import { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { Readable } from 'stream';
import { GatewayConfig } from './config';

// Hop-by-hop headers must never be forwarded to the client (RFC 7230 §6.1).
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

function getUpstreamMap(config: GatewayConfig): Record<string, string> {
  return {
    '/auth':        config.AUTH_SERVICE_URL,
    '/market':      config.MARKET_INGEST_URL,
    '/portfolio':   config.PORTFOLIO_URL,
    '/orders':      config.ORDERS_URL,
    '/risk':        config.RISK_URL,
    '/backtest':    config.BACKTEST_URL,
    '/features':    config.FEATURE_BUILDER_URL,
    '/rl/train':    config.RL_TRAIN_URL,
    '/rl/infer':    config.RL_INFER_URL,
  };
}

// Per-prefix timeout overrides. Any prefix not listed uses GATEWAY_DEFAULT_TIMEOUT_MS.
function getTimeoutOverrides(config: GatewayConfig): Record<string, number> {
  return {
    '/rl/train': config.GATEWAY_RL_TRAIN_TIMEOUT_MS,
  };
}

async function proxyTo(
  upstream: string,
  req: FastifyRequest,
  reply: FastifyReply,
  timeoutMs: number,
): Promise<void> {
  const url = `${upstream}${req.url}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // req.body is always Buffer|null because index.ts registers a catch-all buffer
  // parser (removeAllContentTypeParsers + addContentTypeParser(/.*/, 'buffer')).
  // We never call JSON.stringify here — raw bytes go through untouched regardless
  // of content-type, preserving multipart/binary payloads.
  const hasBody = req.method !== 'GET' && req.method !== 'HEAD';
  const rawBody = hasBody && req.body != null ? (req.body as Buffer) : undefined;

  // Build outbound headers manually so we never accidentally forward hop-by-hop
  // or host headers from the inbound request. content-type is only included when
  // there is actually a body to send — some upstreams reject content-type on
  // bodyless requests.
  const outHeaders: Record<string, string> = {
    'x-trace-id': (req as any).traceId,
    ...(req.headers.authorization ? { authorization: req.headers.authorization } : {}),
    ...(rawBody !== undefined && req.headers['content-type']
      ? { 'content-type': req.headers['content-type'] as string }
      : {}),
  };

  const options: RequestInit = {
    method: req.method,
    headers: outHeaders,
    signal: controller.signal,
    // Buffer extends Uint8Array; explicit cast satisfies TypeScript's BodyInit constraint.
    ...(rawBody !== undefined ? { body: new Uint8Array(rawBody) } : {}),
  };

  try {
    const res = await fetch(url, options);
    clearTimeout(timer);

    reply.status(res.status);
    res.headers.forEach((val, key) => {
      if (!HOP_BY_HOP.has(key)) {
        reply.header(key, val);
      }
    });

    if (res.body) {
      return reply.send(
        Readable.fromWeb(res.body as Parameters<typeof Readable.fromWeb>[0]),
      );
    }
    return reply.send('');
  } catch (err) {
    clearTimeout(timer);

    if ((err as Error).name === 'AbortError') {
      req.log.warn({ upstream, url, timeoutMs }, 'Upstream request timed out');
      return reply.status(504).send({ error: 'Upstream timeout' });
    }

    // Log the real error (with host/port) server-side only. Never forward
    // internal topology details to the client.
    req.log.error({ err, upstream, url }, 'Upstream request failed');
    return reply.status(502).send({ error: 'Upstream unavailable' });
  }
}

export function registerRoutes(app: FastifyInstance, config: GatewayConfig) {
  app.get('/health', async (_req, reply) => {
    reply.send({ status: 'ok', service: 'api-gateway' });
  });

  const UPSTREAM = getUpstreamMap(config);
  const TIMEOUT_OVERRIDES = getTimeoutOverrides(config);
  const defaultTimeout = config.GATEWAY_DEFAULT_TIMEOUT_MS;

  for (const [prefix, upstream] of Object.entries(UPSTREAM)) {
    const timeoutMs = TIMEOUT_OVERRIDES[prefix] ?? defaultTimeout;
    app.all(prefix, async (req, reply) => proxyTo(upstream, req, reply, timeoutMs));
    app.all(`${prefix}/*`, async (req, reply) => proxyTo(upstream, req, reply, timeoutMs));
  }
}
