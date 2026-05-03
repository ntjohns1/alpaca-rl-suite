import { Pool, PoolClient } from 'pg';
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

  // Runs fn inside a serialised BEGIN/COMMIT block. SELECT FOR UPDATE inside fn
  // ensures concurrent callers see each other's writes before logging prior values.
  private async withTransaction<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const result = await fn(client);
      await client.query('COMMIT');
      return result;
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  // Atomically reads the prior portfolio_value and replaces it.
  // `asOf` should be the upstream snapshot's own created_at so that
  // portfolio_value_updated_at reflects data age, not wall-clock write time.
  async updatePortfolioValue(
    portfolioValue: number,
    asOf: Date = new Date(),
  ): Promise<{ prior: number | null }> {
    return this.withTransaction(async (client) => {
      const prior = await client.query<{ portfolio_value: string | null }>(
        `SELECT portfolio_value FROM risk_state WHERE id = 1 FOR UPDATE`,
      );
      await client.query(
        `UPDATE risk_state
            SET portfolio_value = $1,
                portfolio_value_updated_at = $2,
                updated_at = NOW()
          WHERE id = 1`,
        [portfolioValue, asOf],
      );
      const raw = prior.rows[0]?.portfolio_value ?? null;
      return { prior: raw == null ? null : Number(raw) };
    });
  }

  // No transaction needed: both concurrent callers produce the same end state
  // (kill_switch = enabled), and the last-writer-wins for `reason` is the
  // expected conflict-resolution behaviour (both callers halt the system).
  async setKillSwitch(enabled: boolean, reason: string | null) {
    await this.pool.query(
      `UPDATE risk_state SET kill_switch = $1, reason = $2, updated_at = NOW() WHERE id = 1`,
      [enabled, reason],
    );
  }

  // No transaction needed: updateDailyLoss is called from a single source
  // (strategy-runner) with the authoritative running total. Concurrent writes
  // from two runner instances would be a deployment misconfiguration, not a
  // correctness case this service is responsible for.
  async updateDailyLoss(lossUsd: number) {
    await this.pool.query(
      `UPDATE risk_state SET daily_loss_usd = $1, updated_at = NOW() WHERE id = 1`,
      [lossUsd],
    );
  }

  // Atomically reads the prior daily_loss_usd and resets it to 0.
  async resetDailyLoss(): Promise<{ prior: number }> {
    return this.withTransaction(async (client) => {
      const prior = await client.query<{ daily_loss_usd: string }>(
        `SELECT daily_loss_usd FROM risk_state WHERE id = 1 FOR UPDATE`,
      );
      await client.query(
        `UPDATE risk_state SET daily_loss_usd = 0, updated_at = NOW() WHERE id = 1`,
      );
      return { prior: Number(prior.rows[0]?.daily_loss_usd ?? 0) };
    });
  }

  async close() {
    await this.pool.end();
  }
}
