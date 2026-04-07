import { Config } from '@alpaca-rl/config';
import { v4 as uuidv4 } from 'uuid';

interface SymbolScore {
  symbol: string;
  action: number; // 0=SHORT 1=HOLD 2=LONG
  qValues?: number[];
}

export class RunnerScheduler {
  private running = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private _symbols: string[];

  constructor(private config: Config) {
    this._symbols = (process.env.TRADING_SYMBOLS ?? 'AAPL,MSFT,GOOGL').split(',');
  }

  isRunning() { return this.running; }
  symbols()   { return this._symbols; }

  start() {
    if (this.running) return;
    this.running = true;
    // Tick every 60 seconds
    this.timer = setInterval(() => this.tick().catch(console.error), 60_000);
    console.log('Strategy runner started');
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.running = false;
    console.log('Strategy runner stopped');
  }

  async tick() {
    const traceId = uuidv4();
    try {
      // 1. Check kill switch
      const riskRes = await fetch(`${this.config.RISK_URL}/risk/state`);
      if (!riskRes.ok) { console.warn('[runner] risk service unavailable'); return; }
      const riskState = await riskRes.json() as any;
      if (riskState.kill_switch) { console.warn('[runner] kill switch active, skipping tick'); return; }

      // 2. Per symbol: build state → infer → collect scores
      const scores: SymbolScore[] = [];
      for (const symbol of this._symbols) {
        try {
          const state = await this.buildState(symbol);
          if (!state) continue;
          const inferRes = await fetch(`${this.config.RL_INFER_URL}/infer/action`, {
            method: 'POST',
            headers: { 'content-type': 'application/json', 'x-trace-id': traceId },
            body: JSON.stringify({ symbol, state, traceId }),
          });
          if (!inferRes.ok) continue;
          const infer = await inferRes.json() as any;
          scores.push({ symbol, action: infer.action, qValues: infer.qValues });
        } catch (err) {
          console.error(`[runner] infer error for ${symbol}:`, err);
        }
      }

      // 3. Allocate & submit
      const trades = this.allocate(scores);
      for (const trade of trades) {
        await this.submitTrade(trade, traceId);
      }

      // 4. Sync portfolio
      await fetch(`${this.config.PORTFOLIO_URL}/portfolio/sync`, { method: 'POST' }).catch(() => {});
    } catch (err) {
      console.error('[runner] tick error:', err);
    }
  }

  private async buildState(symbol: string): Promise<number[] | null> {
    const res = await fetch(
      `${this.config.MARKET_INGEST_URL}/market/bars/${symbol}?timeframe=1d&limit=30`,
    );
    if (!res.ok) return null;
    const bars = await res.json() as any[];
    if (bars.length < 22) return null;

    // 20-element state vector from feature-builder (10 technical + 10 SHARADAR).
    // The feature-builder is the single source of truth; no fallback —
    // a partial/fake vector would produce garbage predictions.
    const featRes = await fetch(
      `${this.config.FEATURE_BUILDER_URL}/features/latest/${symbol}`,
    ).catch(() => null);

    if (featRes?.ok) {
      const feat = await featRes.json() as any;
      return feat.state_vector ?? null;
    }

    console.warn(`[runner] feature-builder unavailable for ${symbol}, skipping inference`);
    return null;
  }

  private allocate(scores: SymbolScore[]): Array<{symbol: string; side: 'buy'|'sell'; notional: number}> {
    const trades: Array<{symbol: string; side: 'buy'|'sell'; notional: number}> = [];
    const equity = 100_000; // TODO: pull from portfolio service
    const maxPerSymbol = equity * this.config.MAX_POSITION_SIZE_PCT;

    for (const s of scores) {
      if (s.action === 2) { // LONG
        trades.push({ symbol: s.symbol, side: 'buy', notional: maxPerSymbol });
      } else if (s.action === 0) { // SHORT
        trades.push({ symbol: s.symbol, side: 'sell', notional: maxPerSymbol });
      }
      // action=1 (HOLD) → no trade
    }
    return trades;
  }

  private async submitTrade(
    trade: { symbol: string; side: 'buy'|'sell'; notional: number },
    traceId: string,
  ) {
    const idempotencyKey = `${trade.symbol}-${trade.side}-${Date.now()}`;

    // Risk check first
    const checkRes = await fetch(`${this.config.RISK_URL}/risk/check`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ notional: trade.notional, symbol: trade.symbol }),
    });
    if (!checkRes.ok) {
      const body = await checkRes.json() as any;
      console.warn(`[runner] risk check blocked ${trade.symbol}: ${body.reason}`);
      return;
    }

    await fetch(`${this.config.ORDERS_URL}/orders`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-trace-id': traceId },
      body: JSON.stringify({
        symbol: trade.symbol,
        side: trade.side,
        notional: trade.notional,
        orderType: 'market',
        timeInForce: 'day',
        idempotencyKey,
        traceId,
      }),
    });
  }
}
