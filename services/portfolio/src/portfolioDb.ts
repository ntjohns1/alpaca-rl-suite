import { Pool } from 'pg';
import { Config } from '@alpaca-rl/config';

export class PortfolioDb {
  private pool: Pool;

  constructor(config: Config) {
    this.pool = new Pool({ connectionString: config.DATABASE_URL });
  }

  async savePositionSnapshot(positions: any[]) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      for (const p of positions) {
        await client.query(
          `INSERT INTO position_snapshot
             (symbol, qty, avg_entry_price, market_value, unrealized_pl, unrealized_plpc, current_price)
           VALUES ($1,$2,$3,$4,$5,$6,$7)`,
          [p.symbol, p.qty, p.avg_entry_price, p.market_value,
           p.unrealized_pl, p.unrealized_plpc, p.current_price],
        );
      }
      await client.query('COMMIT');
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  async saveAccountSnapshot(account: any) {
    await this.pool.query(
      `INSERT INTO account_snapshot
         (equity, cash, buying_power, portfolio_value, daily_pl, raw_account)
       VALUES ($1,$2,$3,$4,$5,$6)`,
      [account.equity, account.cash, account.buying_power,
       account.portfolio_value, account.last_equity
         ? parseFloat(account.equity) - parseFloat(account.last_equity) : null,
       JSON.stringify(account)],
    );
  }

  async getLatestPositions() {
    const res = await this.pool.query(
      `SELECT DISTINCT ON (symbol) *
       FROM position_snapshot
       ORDER BY symbol, created_at DESC`,
    );
    return res.rows;
  }

  async getLatestAccount() {
    const res = await this.pool.query(
      `SELECT * FROM account_snapshot ORDER BY created_at DESC LIMIT 1`,
    );
    return res.rows[0] ?? null;
  }

  async getAccountHistory(start?: string, end?: string, limit = 500) {
    const params: any[] = [limit];
    let where = '';
    if (start) where += ` AND created_at >= $${params.push(start)}`;
    if (end)   where += ` AND created_at <= $${params.push(end)}`;
    const res = await this.pool.query(
      `SELECT * FROM account_snapshot WHERE 1=1 ${where} ORDER BY created_at DESC LIMIT $1`,
      params,
    );
    return res.rows;
  }

  async close() {
    await this.pool.end();
  }
}
