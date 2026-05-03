import { otelSdk } from './tracing';
import Fastify, { FastifyReply, FastifyRequest } from 'fastify';
import jwt from 'jsonwebtoken';
import client from 'prom-client';
import { loadConfig } from '@alpaca-rl/config';
import { RunnerScheduler } from './runnerScheduler';
import { registry } from '@alpaca-rl/observability';

const config = loadConfig();
const app = Fastify({ logger: true });
const scheduler = new RunnerScheduler(config, app.log);

const BUILD_VERSION = process.env.BUILD_VERSION ?? 'dev';
const GIT_SHA = process.env.GIT_SHA ?? 'unknown';

// process_info gauge so Grafana can join "version → error rate".
new client.Gauge({
  name: 'alpaca_rl_runner_build_info',
  help: 'Build metadata for the running strategy-runner instance',
  labelNames: ['version', 'git_sha', 'trading_mode'] as const,
  registers: [registry],
}).labels(BUILD_VERSION, GIT_SHA, config.TRADING_MODE).set(1);

async function requireAuth(req: FastifyRequest, reply: FastifyReply) {
  const auth = req.headers.authorization;
  if (!auth?.startsWith('Bearer ')) {
    return reply.status(401).send({ error: 'missing bearer token' });
  }
  try {
    // Pin the algorithm — without this, jsonwebtoken accepts `alg: none` and
    // any other algo. JWT_SECRET is HMAC, so HS256 is the only valid choice.
    //
    // TODO: SECURITY DEBT — Symmetric JWT (HS256) shared across all services
    // means any compromised service can forge tokens for all others. Migrate to
    // asymmetric verification (RS256/ES256) using Keycloak's JWKS endpoint.
    // Lower urgency for paper trading, but required before live trading.
    jwt.verify(auth.slice(7), config.JWT_SECRET, { algorithms: ['HS256'] });
  } catch {
    return reply.status(401).send({ error: 'invalid token' });
  }
}

app.post('/runner/start', { preHandler: requireAuth }, async (_req, reply) => {
  scheduler.start();
  return reply.send({ status: 'started' });
});

app.post('/runner/stop', { preHandler: requireAuth }, async (_req, reply) => {
  await scheduler.stop();
  return reply.send({ status: 'stopped' });
});

app.get('/runner/status', async (_req, reply) => {
  return reply.send({ running: scheduler.isRunning(), symbols: scheduler.symbols() });
});

app.post('/runner/tick', { preHandler: requireAuth }, async (_req, reply) => {
  const result = await scheduler.tick();
  return reply.send({ ok: true, ...result, time: new Date().toISOString() });
});

// Liveness: process is up. Always 200 unless event loop is wedged.
app.get('/runner/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'strategy-runner', version: BUILD_VERSION });
});

// Readiness: a "ready" runner is one that has been started and whose tick
// timer is live. If start() was never called or stop() flipped state, k8s
// should not route /runner/tick traffic here.
app.get('/runner/ready', async (_req, reply) => {
  const running = scheduler.isRunning();
  const status = running ? 200 : 503;
  return reply.status(status).send({
    ready: running,
    running,
    symbols: scheduler.symbols(),
  });
});

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

let shuttingDown = false;
async function shutdown(signal: string) {
  if (shuttingDown) return;
  shuttingDown = true;
  app.log.info({ signal }, 'shutdown initiated');
  let exitCode = 0;
  try {
    await scheduler.stop();   // awaits any in-flight tick
    await app.close();        // drain HTTP
    await otelSdk.shutdown(); // flush traces last
  } catch (err) {
    app.log.error({ err: String(err) }, 'error during shutdown');
    exitCode = 1;  // Signal failure to container orchestrator
  } finally {
    process.exit(exitCode);
  }
}

process.on('SIGTERM', () => { void shutdown('SIGTERM'); });
process.on('SIGINT', () => { void shutdown('SIGINT'); });

app.listen({ port: config.STRATEGY_RUNNER_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
  app.log.info(
    {
      port: config.STRATEGY_RUNNER_PORT,
      symbols: scheduler.symbols(),
      tradingMode: config.TRADING_MODE,
      version: BUILD_VERSION,
      gitSha: GIT_SHA,
    },
    'strategy-runner listening',
  );
});
