import { Config } from '@alpaca-rl/config';
import { PortfolioDb } from './portfolioDb';

export class PortfolioService {
  constructor(private config: Config, private db: PortfolioDb) {}

  async syncFromBroker() {
    const [posRes, accRes] = await Promise.all([
      fetch(`${this.config.ALPACA_ADAPTER_URL}/alpaca/positions`),
      fetch(`${this.config.ALPACA_ADAPTER_URL}/alpaca/account`),
    ]);

    if (posRes.ok) {
      const positions = await posRes.json();
      if (Array.isArray(positions) && positions.length > 0) {
        await this.db.savePositionSnapshot(positions);
      }
    }

    if (accRes.ok) {
      const account = await accRes.json();
      await this.db.saveAccountSnapshot(account);
    }
  }
}
