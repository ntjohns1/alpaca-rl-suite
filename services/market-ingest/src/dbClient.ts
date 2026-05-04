import { Pool, PoolClient } from 'pg';
import { Config } from '@alpaca-rl/config';

const ALLOWED_TABLES = new Set(['bar_1m', 'bar_1d']);

// Columns per bar row — must match the INSERT column list exactly.
const BAR_COLS = 9;

// Postgres hard-limits bind parameters to 65535 per query.
// At 9 columns per bar, that caps us at 7281 rows per INSERT.
const CHUNK_SIZE = Math.floor(65535 / BAR_COLS); // 7281

// Runtime guard so interpolated table names can never be attacker-controlled.
// TypeScript's union type enforces this at compile time; this catches any
// bypass (e.g. JSON.parse coercion, tests casting `as any`).
function assertTable(table: string): asserts table is 'bar_1m' | 'bar_1d' {
  if (!ALLOWED_TABLES.has(table)) throw new Error(`invalid table: ${table}`);
}

type Bar = {
  time: string;
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap?: number;
  tradeCount?: number;
};

export class DbClient {
  private pool: Pool;

  constructor(config: Config) {
    this.pool = new Pool({ connectionString: config.DATABASE_URL });
  }

  async upsertBar(table: 'bar_1m' | 'bar_1d', bar: Bar) {
    assertTable(table);
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

  async upsertBarBatch(table: 'bar_1m' | 'bar_1d', bars: Bar[]) {
    if (bars.length === 0) return;
    assertTable(table);

    // Wrap all chunks in one transaction so the batch is all-or-nothing.
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      for (let i = 0; i < bars.length; i += CHUNK_SIZE) {
        await this._insertChunk(client, table, bars.slice(i, i + CHUNK_SIZE));
      }
      await client.query('COMMIT');
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  // Builds a single multi-row INSERT for one chunk (≤ CHUNK_SIZE rows).
  private async _insertChunk(client: PoolClient, table: 'bar_1m' | 'bar_1d', bars: Bar[]) {
    const values: unknown[] = [];
    const placeholders = bars.map((bar, i) => {
      const base = i * BAR_COLS;
      values.push(
        bar.time, bar.symbol, bar.open, bar.high,
        bar.low, bar.close, bar.volume,
        bar.vwap ?? null, bar.tradeCount ?? null,
      );
      return `($${base+1},$${base+2},$${base+3},$${base+4},$${base+5},$${base+6},$${base+7},$${base+8},$${base+9})`;
    });

    await client.query(`
      INSERT INTO ${table} (time, symbol, open, high, low, close, volume, vwap, trade_count)
      VALUES ${placeholders.join(',')}
      ON CONFLICT (time, symbol) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low  = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        vwap = EXCLUDED.vwap,
        trade_count = EXCLUDED.trade_count
    `, values);
  }

  async queryBars(
    table: 'bar_1m' | 'bar_1d',
    symbol: string,
    start?: string,
    end?: string,
    limit = 500,
  ) {
    assertTable(table);
    const params: unknown[] = [symbol, limit];
    let where = 'WHERE symbol = $1';
    if (start) { where += ` AND time >= $${params.push(start)}`; }
    if (end)   { where += ` AND time <= $${params.push(end)}`; }
    const sql = `
      SELECT time, symbol, open, high, low, close, volume, vwap, trade_count
      FROM ${table} ${where}
      ORDER BY time DESC LIMIT $2
    `;
    const res = await this.pool.query(sql, params);
    return res.rows;
  }

  async querySymbols() {
    // UNION (without ALL) already deduplicates across both sides — DISTINCT
    // inside each sub-select would cause a redundant second sort/hash pass.
    const res = await this.pool.query(
      `SELECT symbol FROM bar_1m
       UNION
       SELECT symbol FROM bar_1d
       ORDER BY symbol`,
    );
    return res.rows.map((r: { symbol: string }) => r.symbol);
  }

  async queryBarCount(
    table: 'bar_1m' | 'bar_1d',
    symbol: string,
    start: string,
    end: string,
  ): Promise<number> {
    assertTable(table);
    const res = await this.pool.query(
      `SELECT COUNT(*) as cnt FROM ${table} WHERE symbol = $1 AND time BETWEEN $2 AND $3`,
      [symbol, start, end],
    );
    return parseInt(res.rows[0].cnt, 10);
  }

  async close() {
    await this.pool.end();
  }
}
