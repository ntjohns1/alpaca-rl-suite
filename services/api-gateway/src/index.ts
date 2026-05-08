import './tracing';
import Fastify from 'fastify';
import fastifyJwt from '@fastify/jwt';
import { v4 as uuidv4 } from 'uuid';
import { loadGatewayConfig } from './config';
import { registerRoutes } from './routes';
import { errorHandler } from './middleware/errorHandler';
import { correlationId } from './middleware/correlationId';
import { authenticate } from './middleware/auth';
import { registry } from '@alpaca-rl/observability';

const config = loadGatewayConfig();

const app = Fastify({
  logger: {
    level: 'info',
    serializers: {
      req(req) {
        return {
          method: req.method,
          url: req.url,
          traceId: (req as any).traceId,
        };
      },
    },
  },
  genReqId: () => uuidv4(),
});

app.setErrorHandler(errorHandler);

// JWT plugin — consumed by the authenticate onRequest hook.
app.register(fastifyJwt, { secret: config.JWT_SECRET });

// This gateway is a reverse proxy and must not alter request bodies.
// Replacing all content-type parsers with a catch-all buffer parser ensures
// req.body is always a raw Buffer, preventing JSON.stringify from corrupting
// multipart/form-data or binary payloads.
app.removeAllContentTypeParsers();
app.addContentTypeParser(/.*/, { parseAs: 'buffer' }, (_req, body, done) => {
  done(null, body);
});

// Hooks run in registration order: trace ID first, then JWT.
app.addHook('onRequest', correlationId);
app.addHook('onRequest', authenticate);

registerRoutes(app, config);

const start = async () => {
  try {
    // Metrics are served on a dedicated internal port so they are never reachable
    // through the public gateway. Prometheus should scrape PROMETHEUS_PORT directly;
    // the ingress/load-balancer should not expose it externally.
    const metricsApp = Fastify({ logger: false });
    metricsApp.get('/metrics', async (_req, reply) => {
      reply.header('Content-Type', registry.contentType);
      return reply.send(await registry.metrics());
    });
    await metricsApp.listen({ port: config.PROMETHEUS_PORT, host: '0.0.0.0' });

    await app.listen({ port: config.API_GATEWAY_PORT, host: '0.0.0.0' });
    app.log.info(
      { port: config.API_GATEWAY_PORT, metricsPort: config.PROMETHEUS_PORT },
      'API Gateway started',
    );
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

start();
