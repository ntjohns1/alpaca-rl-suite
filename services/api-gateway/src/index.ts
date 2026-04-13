import './tracing';
import Fastify from 'fastify';
import { v4 as uuidv4 } from 'uuid';
import { loadConfig } from '@alpaca-rl/config';
import { registerRoutes } from './routes';
import { errorHandler } from './middleware/errorHandler';
import { correlationId } from './middleware/correlationId';
import { registry } from '@alpaca-rl/observability';

const config = loadConfig();

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
app.addHook('onRequest', correlationId);

registerRoutes(app);

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

const start = async () => {
  try {
    await app.listen({ port: config.API_GATEWAY_PORT, host: '0.0.0.0' });
    console.log(`API Gateway listening on port ${config.API_GATEWAY_PORT}`);
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
};

start();
