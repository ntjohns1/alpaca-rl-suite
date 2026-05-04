import { Config } from '@alpaca-rl/config';
import { BackfillRequest } from '@alpaca-rl/contracts';
import type { FastifyBaseLogger } from 'fastify';
import { DbClient } from './dbClient';
import Alpaca = require('@alpacahq/alpaca-trade-api');

// Must be strictly less than DRAIN_TIMEOUT_MS in index.ts (20_000) so the
// fetch rejects and the job's catch block settles the promise before the
// SIGTERM drain deadline fires.
const FETCH_TIMEOUT_MS = 15_000;

export class BackfillJob {
  constructor(
    private config: Config,
    private db: DbClient,
    private log: FastifyBaseLogger,
  ) {}

  async run(req: BackfillRequest) {
    const table = req.timeframe === '1m' ? 'bar_1m' : 'bar_1d';
    const tf = req.timeframe === '1m' ? '1Min' : '1Day';

    // Create the Alpaca client once per job, not once per symbol.
    const alpaca = new (Alpaca as any)({
      keyId: this.config.ALPACA_API_KEY,
      secretKey: this.config.ALPACA_API_SECRET,
      paper: this.config.TRADING_MODE === 'paper',
      baseUrl: this.config.ALPACA_BASE_URL,
    });

    for (const symbol of req.symbols) {
      try {
        this.log.info({ symbol, timeframe: req.timeframe, start: req.startDate, end: req.endDate }, 'backfill: starting symbol');
        const bars = await this.fetchBars(alpaca, symbol, tf, req.startDate, req.endDate);
        if (bars.length === 0) {
          this.log.warn({ symbol }, 'backfill: no bars returned');
          continue;
        }
        // Alpaca SDK v3+ uses PascalCase fields; older versions use single-letter aliases.
        const mapped = bars.map((b: any) => ({
          time:       b.Timestamp  ?? b.t,
          symbol,
          open:       b.OpenPrice  ?? b.o,
          high:       b.HighPrice  ?? b.h,
          low:        b.LowPrice   ?? b.l,
          close:      b.ClosePrice ?? b.c,
          volume:     b.Volume     ?? b.v,
          vwap:       b.VWAP       ?? b.vw,
          tradeCount: b.TradeCount ?? b.n,
        }));
        await this.db.upsertBarBatch(table, mapped);
        this.log.info({ symbol, count: mapped.length }, 'backfill: upserted bars');
      } catch (err) {
        this.log.error({ err, symbol }, 'backfill: symbol failed, continuing');
      }
    }
  }

  private async fetchBars(
    alpaca: any,
    symbol: string,
    timeframe: string,
    start: string,
    end: string,
  ) {
    // Race the generator against a hard deadline. The Alpaca SDK doesn't
    // support AbortController, so this is the only way to bound stalled fetches.
    const doFetch = async () => {
      const gen = alpaca.getBarsV2(symbol, {
        timeframe,
        start,
        end,
        limit: 10000,
        feed: 'iex',
      });
      const bars: any[] = [];
      for await (const bar of gen) {
        bars.push(bar);
      }
      return bars;
    };

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(
        () => reject(new Error(`fetchBars timed out after ${FETCH_TIMEOUT_MS}ms`)),
        FETCH_TIMEOUT_MS,
      ),
    );

    return Promise.race([doFetch(), timeout]);
  }
}
