import { Config } from '@alpaca-rl/config';
import { BackfillRequest } from '@alpaca-rl/contracts';
import { DbClient } from './dbClient';
import Alpaca = require('@alpacahq/alpaca-trade-api');

export class BackfillJob {
  constructor(private config: Config, private db: DbClient) {}

  async run(req: BackfillRequest) {
    const table = req.timeframe === '1m' ? 'bar_1m' : 'bar_1d';
    const tf = req.timeframe === '1m' ? '1Min' : '1Day';

    for (const symbol of req.symbols) {
      console.log(`Backfilling ${symbol} ${req.timeframe} ${req.startDate}→${req.endDate}`);
      const bars = await this.fetchBars(symbol, tf, req.startDate, req.endDate);
      if (bars.length === 0) {
        console.warn(`No bars returned for ${symbol}`);
        continue;
      }
      const mapped = bars.map((b: any) => ({
        time: b.Timestamp ?? b.t,
        symbol,
        open: b.OpenPrice ?? b.o,
        high: b.HighPrice ?? b.h,
        low: b.LowPrice ?? b.l,
        close: b.ClosePrice ?? b.c,
        volume: b.Volume ?? b.v,
        vwap: b.VWAP ?? b.vw,
        tradeCount: b.TradeCount ?? b.n,
      }));
      await this.db.upsertBarBatch(table, mapped);
      console.log(`Upserted ${mapped.length} bars for ${symbol}`);
    }
  }

  private async fetchBars(symbol: string, timeframe: string, start: string, end: string) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const alpaca = new (Alpaca as any)({
      keyId: this.config.ALPACA_API_KEY,
      secretKey: this.config.ALPACA_API_SECRET,
      paper: this.config.TRADING_MODE === 'paper',
      baseUrl: this.config.ALPACA_BASE_URL,
    });

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
  }
}
