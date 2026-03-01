import './tracing';
import Fastify from 'fastify';
import { loadConfig } from '@alpaca-rl/config';
import { RunnerScheduler } from './runnerScheduler';
import { registry } from '@alpaca-rl/observability';

const config = loadConfig();
const app = Fastify({ logger: true });
const scheduler = new RunnerScheduler(config);

app.post('/runner/start', async (_req, reply) => {
  scheduler.start();
  return reply.send({ status: 'started' });
});

app.post('/runner/stop', async (_req, reply) => {
  scheduler.stop();
  return reply.send({ status: 'stopped' });
});

app.get('/runner/status', async (_req, reply) => {
  return reply.send({ running: scheduler.isRunning(), symbols: scheduler.symbols() });
});

app.post('/runner/tick', async (_req, reply) => {
  await scheduler.tick();
  return reply.send({ ok: true, time: new Date().toISOString() });
});

app.get('/runner/health', async (_req, reply) => {
  reply.send({ status: 'ok', service: 'strategy-runner' });
});

app.get('/metrics', async (_req, reply) => {
  reply.header('Content-Type', registry.contentType);
  return reply.send(await registry.metrics());
});

app.listen({ port: config.STRATEGY_RUNNER_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
  app.log.info(`Strategy Runner listening on port ${config.STRATEGY_RUNNER_PORT}`);
});
