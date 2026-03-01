import { Pool } from 'pg';
import { Config } from '@alpaca-rl/config';

export class DbClient {
  private pool: Pool;

  constructor(config: Config) {
    this.pool = new Pool({ connectionString: config.DATABASE_URL });
  }

  async upsertBar(
    table: 'bar_1m' | 'bar_1d',
    bar: {
      time: string;
      symbol: string;
      open: number;
      high: number;
      low: number;
      close: number;
      volume: number;
      vwap?: number;
      tradeCount?: number;
    },
  ) {
    const sql = `
      INSERT INTO ${table} (time, symbol, open, high, low, close, volume, vwap, trade_count)
      VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
      ON CONFLICT (time, symbol) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low  = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        vwap = EXCLUDED.vwap,
        trade_count = EXCLUDED.trade_count
    `;
    await this.pool.query(sql, [
      bar.time, bar.symbol, bar.open, bar.high,
      bar.low, bar.close, bar.volume,
      bar.vwap ?? null, bar.tradeCount ?? null,
    ]);
  }

  async upsertBarBatch(table: 'bar_1m' | 'bar_1d', bars: Parameters<DbClient['upsertBar']>[1][]) {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      for (const bar of bars) {
        await this.upsertBar(table, bar);
      }
      await client.query('COMMIT');
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  async queryBars(
    table: 'bar_1m' | 'bar_1d',
    symbol: string,
    start?: string,
    end?: string,
    limit = 500,
  ) {
    const params: any[] = [symbol, limit];
    let where = 'WHERE symbol = $1';
    if (start) { where += ` AND time >= $${params.push(start)}`; }
    if (end)   { where += ` AND time <= $${params.push(end)}`; }
    const sql = `SELECT * FROM ${table} ${where} ORDER BY time DESC LIMIT $2`;
    const res = await this.pool.query(sql, params);
    return res.rows;
  }

  async querySymbols() {
    const res = await this.pool.query(
      `SELECT DISTINCT symbol FROM bar_1d ORDER BY symbol`,
    );
    return res.rows.map((r: any) => r.symbol);
  }

  async close() {
    await this.pool.end();
  }
}
