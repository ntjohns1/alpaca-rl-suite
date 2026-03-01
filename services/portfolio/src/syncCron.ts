import { Config } from '@alpaca-rl/config';
import { PortfolioService } from './portfolioService';
import { PortfolioDb } from './portfolioDb';

export class SyncCron {
  private timer: ReturnType<typeof setInterval> | null = null;
  private svc: PortfolioService;

  constructor(private config: Config) {
    const db = new PortfolioDb(config);
    this.svc = new PortfolioService(config, db);
  }

  start(intervalMs = 60_000) {
    if (this.timer) return;
    // Sync immediately on start, then on interval
    this.run().catch(console.error);
    this.timer = setInterval(() => this.run().catch(console.error), intervalMs);
    console.log(`Portfolio sync cron started (interval=${intervalMs}ms)`);
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  private async run() {
    try {
      await this.svc.syncFromBroker();
    } catch (err) {
      console.error('[portfolio-sync]', err);
    }
  }
}
