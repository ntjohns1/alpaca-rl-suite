import { Pool } from 'pg';
import { Config } from '@alpaca-rl/config';

export class RiskDb {
  private pool: Pool;

  constructor(config: Config) {
    this.pool = new Pool({ connectionString: config.DATABASE_URL });
  }

  async getState() {
    const res = await this.pool.query(
      `SELECT * FROM risk_state ORDER BY id LIMIT 1`,
    );
    return res.rows[0];
  }

  async setKillSwitch(enabled: boolean, reason: string | null) {
    await this.pool.query(
      `UPDATE risk_state SET kill_switch = $1, reason = $2, updated_at = NOW()`,
      [enabled, reason],
    );
  }

  async updateDailyLoss(lossUsd: number) {
    await this.pool.query(
      `UPDATE risk_state SET daily_loss_usd = $1, updated_at = NOW()`,
      [lossUsd],
    );
  }

  async resetDailyLoss() {
    await this.pool.query(
      `UPDATE risk_state SET daily_loss_usd = 0, updated_at = NOW()`,
    );
  }

  async close() {
    await this.pool.end();
  }
}
