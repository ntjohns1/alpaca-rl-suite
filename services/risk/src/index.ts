import './tracing';
import { loadConfig } from '@alpaca-rl/config';
import { RiskDb } from './riskDb.js';
import { createApp } from './app.js';
import { PortfolioSyncCron } from './portfolioSync.js';

const config = loadConfig();

// Guard against misconfigured intervals: if the sync interval is >= half the
// staleness threshold, the staleness gate will fire between syncs.
const { RISK_PORTFOLIO_SYNC_INTERVAL_MS: syncMs, MAX_PORTFOLIO_STALENESS_S: stalenessS } = config;
if (syncMs * 2 >= stalenessS * 1000) {
  throw new Error(
    `RISK_PORTFOLIO_SYNC_INTERVAL_MS (${syncMs} ms) must be < half of ` +
    `MAX_PORTFOLIO_STALENESS_S (${stalenessS} s = ${stalenessS * 1000} ms). ` +
    `Reduce the sync interval or increase the staleness threshold.`,
  );
}

const db = new RiskDb(config);
const app = createApp(config, db);
const cron = new PortfolioSyncCron(config, db, app.log);

const SHUTDOWN_TIMEOUT_MS = 10_000;

async function shutdown(signal: string) {
  app.log.info({ signal }, 'shutdown starting');
  cron.stop();

  // Hard-kill timer: if close() hangs (stuck request or deadlocked query),
  // Kubernetes will SIGKILL after its own grace period anyway — this ensures
  // we flush logs and exit cleanly on our own schedule first.
  const killer = setTimeout(() => {
    app.log.error('shutdown timed out — force exit');
    process.exit(1);
  }, SHUTDOWN_TIMEOUT_MS).unref();

  await app.close();  // drains in-flight requests
  await db.close();   // releases pg pool
  clearTimeout(killer);
  process.exit(0);
}

process.on('SIGTERM', () => { shutdown('SIGTERM').catch((err) => { console.error(err); process.exit(1); }); });
process.on('SIGINT',  () => { shutdown('SIGINT').catch((err)  => { console.error(err); process.exit(1); }); });

app.listen({ port: config.RISK_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
  cron.start();
});
