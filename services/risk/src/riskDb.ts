import { Pool } from 'pg';
import { Config } from '@alpaca-rl/config';

export class RiskDb {
  private pool: Pool;

  constructor(config: Config) {
    this.pool = new Pool({ connectionString: config.DATABASE_URL });
  }

  async getState() {
    const res = await this.pool.query(
      `SELECT * FROM risk_state WHERE id = 1`,
    );
    if (res.rows.length === 0) {
      // The init.sql migration inserts the singleton row. If it's missing,
      // every downstream check would TypeError on undefined access.
      throw new Error('risk_state row missing — run database migrations');
    }
    return res.rows[0];
  }

  async updatePortfolioValue(portfolioValue: number) {
    await this.pool.query(
      `UPDATE risk_state
          SET portfolio_value = $1,
              portfolio_value_updated_at = NOW(),
              updated_at = NOW()
        WHERE id = 1`,
      [portfolioValue],
    );
  }

  async setKillSwitch(enabled: boolean, reason: string | null) {
    await this.pool.query(
      `UPDATE risk_state SET kill_switch = $1, reason = $2, updated_at = NOW() WHERE id = 1`,
      [enabled, reason],
    );
  }

  async updateDailyLoss(lossUsd: number) {
    await this.pool.query(
      `UPDATE risk_state SET daily_loss_usd = $1, updated_at = NOW() WHERE id = 1`,
      [lossUsd],
    );
  }

  async resetDailyLoss() {
    await this.pool.query(
      `UPDATE risk_state SET daily_loss_usd = 0, updated_at = NOW() WHERE id = 1`,
    );
  }

  async close() {
    await this.pool.end();
  }
}
