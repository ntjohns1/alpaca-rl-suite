import { Config } from '@alpaca-rl/config';
import { randomUUID } from 'node:crypto';
import type { FastifyBaseLogger } from 'fastify';
import { z } from 'zod';
import {
  runnerTicksTotal,
  runnerTickDurationMs,
  runnerSignalsTotal,
  runnerOrdersSubmittedTotal,
  runnerEquityUsd,
  killSwitchActive,
} from '@alpaca-rl/observability';

interface SymbolScore {
  symbol: string;
  action: 0 | 1 | 2; // 0=SHORT 1=HOLD 2=LONG
  qValues?: number[];
}

interface Trade {
  symbol: string;
  side: 'buy' | 'sell';
  notional: number;
}

// Logger shape matches Fastify's pino logger. We only need a subset; defining
// it locally as a structural type keeps tests free of a Fastify dependency.
type Logger = Pick<FastifyBaseLogger, 'info' | 'warn' | 'error'> & {
  debug?: FastifyBaseLogger['debug'];
};

const RiskStateSchema = z.object({
  // Fail-closed: kill_switch is REQUIRED. A missing field = treat as ON.
  kill_switch: z.boolean(),
});

const InferResponseSchema = z.object({
  action: z.union([z.literal(0), z.literal(1), z.literal(2)]),
  qValues: z.array(z.number()).optional(),
});

const FeatureResponseSchema = z.object({
  state_vector: z.array(z.number()).nullable().optional(),
});

const AccountSchema = z.object({
  equity: z.union([z.string(), z.number()]),
}).passthrough();

const PositionSchema = z.object({
  symbol: z.string(),
  qty: z.union([z.string(), z.number()]).optional(),
  market_value: z.union([z.string(), z.number()]).optional(),
}).passthrough();

const ACTION_LABEL = ['SHORT', 'HOLD', 'LONG'] as const;

export class RunnerScheduler {
  private running = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private inFlight: Promise<void> | null = null;
  private _symbols: string[];
  private readonly tickIntervalMs: number;
  private readonly fetchTimeoutMs: number;
  private readonly minOrderNotional: number;
  private readonly log: Logger;

  constructor(private config: Config, log: Logger) {
    this.log = log;
    this._symbols = parseSymbols(process.env.TRADING_SYMBOLS);
    this.tickIntervalMs = parsePositiveInt(process.env.TICK_INTERVAL_MS, 60_000);
    this.fetchTimeoutMs = parsePositiveInt(process.env.RUNNER_FETCH_TIMEOUT_MS, 5_000);
    // Floor for rebalance orders. Market value fluctuates by a few dollars
    // between ticks from price movement alone — without a floor, every tick
    // generates tiny $1-$3 "rebalance" orders that are noise, not signal.
    // Alpaca requires >= $1 notional for fractional shares.
    const rawMinNotional = parsePositiveFloat(process.env.MIN_ORDER_NOTIONAL_USD, 5);
    if (rawMinNotional < 1) {
      throw new Error('MIN_ORDER_NOTIONAL_USD must be >= 1 (broker minimum for fractional shares)');
    }
    this.minOrderNotional = rawMinNotional;
  }

  isRunning() { return this.running; }
  symbols()   { return this._symbols; }

  start() {
    if (this.running) return;
    this.running = true;
    this.timer = setInterval(() => this.runTick(), this.tickIntervalMs);
    this.log.info({ tickIntervalMs: this.tickIntervalMs, symbols: this._symbols }, 'strategy-runner started');
  }

  async stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.running = false;
    if (this.inFlight) {
      try { await this.inFlight; } catch { /* already logged */ }
    }
    this.log.info({}, 'strategy-runner stopped');
  }

  /**
   * Public entry for HTTP /runner/tick. Returns `{executed: false}` if a tick
   * is already running, so the HTTP handler can tell the caller their request
   * was a no-op (otherwise an operator forcing a tick can't distinguish "ran"
   * from "skipped due to overlap").
   * 
   * Race-safe: the guard and assignment happen atomically in runTick().
   */
  async tick(): Promise<{ executed: boolean; reason?: 'overlap' }> {
    const p = this.runTick();
    if (p === null) return { executed: false, reason: 'overlap' };
    await p;
    return { executed: true };
  }

  private runTick(): Promise<void> | null {
    // Atomic check-and-set: if already in flight, return null immediately.
    // In Node's single-threaded event loop the synchronous path from the
    // guard through the assignment is uninterruptible, so two concurrent
    // HTTP /runner/tick calls cannot both pass the check.
    if (this.inFlight !== null) {
      this.log.warn({}, '[runner] tick skipped: previous tick still running');
      runnerTicksTotal.inc({ outcome: 'skipped_overlap' });
      return null;
    }
    const p = this.doTick().finally(() => { this.inFlight = null; });
    this.inFlight = p;
    return p;
  }

  private async doTick(): Promise<void> {
    const traceId = randomTraceId();
    const endTimer = runnerTickDurationMs.startTimer();
    try {
      // 1. Kill switch (fail-closed: any failure to confirm OFF = treat as ON).
      const killOn = await this.isKillSwitchOn(traceId);
      killSwitchActive.set(killOn ? 1 : 0);
      if (killOn) {
        runnerTicksTotal.inc({ outcome: 'skipped_kill_switch' });
        return;
      }

      // 2. Fetch equity + current positions in parallel. Both are required
      // for correct sizing; missing either = skip tick. Treating unknown
      // positions as "no positions" caused the original $100k-equity class
      // of bug — every LONG would re-buy to full target on top of an
      // existing position whenever portfolio service flaked.
      const [equity, positions] = await Promise.all([
        this.fetchEquity(traceId),
        this.fetchPositions(traceId),
      ]);
      if (equity === null) {
        this.log.warn({ traceId }, '[runner] equity unknown — skipping tick');
        runnerTicksTotal.inc({ outcome: 'skipped_risk_unavailable' });
        return;
      }
      if (positions === null) {
        this.log.warn({ traceId }, '[runner] positions unknown — skipping tick');
        runnerTicksTotal.inc({ outcome: 'skipped_risk_unavailable' });
        return;
      }
      runnerEquityUsd.set(equity);

      // 3. Per-symbol inference in parallel.
      const scores = await this.collectScores(traceId);

      // 4. Allocate (size delta vs. current position) and submit.
      const trades = this.allocate(scores, positions, equity);
      await Promise.all(trades.map((t) => this.submitTrade(t, traceId)));

      // 5. Sync portfolio (best-effort).
      await this.fetchJson(`${this.config.PORTFOLIO_URL}/portfolio/sync`, {
        method: 'POST',
        traceId,
      }).catch((err) => {
        this.log.warn({ traceId, err: String(err) }, '[runner] portfolio/sync failed');
      });

      runnerTicksTotal.inc({ outcome: 'success' });
    } catch (err) {
      this.log.error({ traceId, err: String(err) }, '[runner] tick error');
      runnerTicksTotal.inc({ outcome: 'error' });
    } finally {
      endTimer();
    }
  }

  // ── Kill switch (fail-closed) ──────────────────────────────────────

  private async isKillSwitchOn(traceId: string): Promise<boolean> {
    try {
      const res = await this.fetchJson(`${this.config.RISK_URL}/risk/state`, { traceId });
      if (!res.ok) {
        this.log.warn({ traceId, status: res.status }, '[runner] risk service unavailable — fail-closed');
        return true;
      }
      const parsed = RiskStateSchema.safeParse(res.body);
      if (!parsed.success) {
        this.log.error({ traceId, issues: parsed.error.issues }, '[runner] risk state malformed — fail-closed');
        return true;
      }
      return parsed.data.kill_switch;
    } catch (err) {
      this.log.warn({ traceId, err: String(err) }, '[runner] risk check threw — fail-closed');
      return true;
    }
  }

  // ── Portfolio (equity + positions) ─────────────────────────────────

  private async fetchEquity(traceId: string): Promise<number | null> {
    try {
      const res = await this.fetchJson(`${this.config.PORTFOLIO_URL}/portfolio/account`, { traceId });
      if (!res.ok) return null;
      const parsed = AccountSchema.safeParse(res.body);
      if (!parsed.success) return null;
      const eq = Number(parsed.data.equity);
      return Number.isFinite(eq) && eq > 0 ? eq : null;
    } catch {
      return null;
    }
  }

  private async fetchPositions(traceId: string): Promise<Map<string, number> | null> {
    // Returns symbol → market_value (USD), or null when the answer is unknown.
    // Fail-closed: an empty map means "we know there are no positions",
    // null means "we don't know" — the caller must skip the tick on null.
    try {
      const res = await this.fetchJson(`${this.config.PORTFOLIO_URL}/portfolio/positions`, { traceId });
      if (!res.ok) {
        this.log.warn({ traceId, status: res.status }, '[runner] positions HTTP error');
        return null;
      }
      const arr = z.array(PositionSchema).safeParse(res.body);
      if (!arr.success) {
        this.log.warn({ traceId, issues: arr.error.issues }, '[runner] positions response malformed');
        return null;
      }
      const map = new Map<string, number>();
      for (const p of arr.data) {
        const mv = Number(p.market_value ?? 0);
        if (Number.isFinite(mv)) {
          // Accumulate in case portfolio service returns multiple entries for
          // the same symbol (e.g., from partial fills or multi-strategy).
          const existing = map.get(p.symbol) ?? 0;
          map.set(p.symbol, existing + mv);
        }
      }
      return map;
    } catch (err) {
      this.log.warn({ traceId, err: String(err) }, '[runner] positions fetch threw');
      return null;
    }
  }

  // ── Inference ──────────────────────────────────────────────────────

  private async collectScores(traceId: string): Promise<SymbolScore[]> {
    const results = await Promise.all(this._symbols.map(async (symbol) => {
      try {
        const state = await this.buildState(symbol, traceId);
        if (!state) return null;
        const res = await this.fetchJson(`${this.config.RL_INFER_URL}/infer/action`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ symbol, state, traceId }),
          traceId,
        });
        if (!res.ok) return null;
        const parsed = InferResponseSchema.safeParse(res.body);
        if (!parsed.success) {
          this.log.warn({ traceId, symbol, issues: parsed.error.issues }, '[runner] infer response malformed');
          return null;
        }
        runnerSignalsTotal.inc({ symbol, action: ACTION_LABEL[parsed.data.action] });
        return { symbol, action: parsed.data.action, qValues: parsed.data.qValues };
      } catch (err) {
        this.log.error({ traceId, symbol, err: String(err) }, '[runner] infer error');
        return null;
      }
    }));
    return results.filter((s): s is NonNullable<typeof s> => s !== null);
  }

  private async buildState(symbol: string, traceId: string): Promise<number[] | null> {
    // The feature-builder is the single source of truth — no fallback.
    // A partial/synthetic vector would produce garbage predictions.
    const res = await this.fetchJson(
      `${this.config.FEATURE_BUILDER_URL}/features/latest/${symbol}`,
      { traceId },
    ).catch(() => null);

    if (!res || !res.ok) {
      this.log.warn({ traceId, symbol }, '[runner] feature-builder unavailable, skipping inference');
      return null;
    }
    const parsed = FeatureResponseSchema.safeParse(res.body);
    if (!parsed.success || !parsed.data.state_vector) {
      this.log.warn({ traceId, symbol }, '[runner] feature response missing state_vector');
      return null;
    }
    return parsed.data.state_vector;
  }

  // ── Allocation ────────────────────────────────────────────────────

  private allocate(
    scores: SymbolScore[],
    positions: Map<string, number>,
    equity: number,
  ): Trade[] {
    const trades: Trade[] = [];
    const target = equity * this.config.MAX_POSITION_SIZE_PCT;

    for (const s of scores) {
      const currentMv = positions.get(s.symbol) ?? 0;

      if (s.action === 2) {
        const delta = target - currentMv;
        if (delta > this.minOrderNotional) {
          trades.push({ symbol: s.symbol, side: 'buy', notional: round2(delta) });
        }
      } else if (s.action === 0) {
        if (currentMv > this.minOrderNotional) {
          trades.push({ symbol: s.symbol, side: 'sell', notional: round2(currentMv) });
        }
      }
      // action=1 (HOLD) → no trade
    }
    return trades;
  }

  // ── Submission ────────────────────────────────────────────────────

  private async submitTrade(trade: Trade, traceId: string): Promise<void> {
    // Deterministic key: same logical decision (this trace, this symbol, this side)
    // always produces the same key. Retries land on the same row in orders DB
    // (ON CONFLICT DO UPDATE) instead of duplicating.
    const idempotencyKey = `${traceId}-${trade.symbol}-${trade.side}`;

    try {
      const checkRes = await this.fetchJson(`${this.config.RISK_URL}/risk/check`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ notional: trade.notional, symbol: trade.symbol }),
        traceId,
      });
      if (!checkRes.ok) {
        const reason = (checkRes.body as any)?.reason ?? 'unknown';
        // 'portfolio_unsynced' / 'portfolio_stale' are operational failures, not
        // risk decisions — the risk service's PortfolioSyncCron should recover
        // them within MAX_PORTFOLIO_STALENESS_S. We intentionally do NOT retry
        // here: the tick cadence already provides a natural retry on the next
        // interval, and an in-tick retry loop would mask the sync outage in logs.
        const isUnavailable = reason === 'portfolio_unsynced' || reason === 'portfolio_stale';
        this.log.warn({ traceId, symbol: trade.symbol, side: trade.side, reason }, '[runner] risk check blocked');
        runnerOrdersSubmittedTotal.inc({
          symbol: trade.symbol,
          side: trade.side,
          outcome: isUnavailable ? 'risk_unavailable' : 'risk_blocked',
        });
        return;
      }

      const orderRes = await this.fetchJson(`${this.config.ORDERS_URL}/orders`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          symbol: trade.symbol,
          side: trade.side,
          notional: trade.notional,
          orderType: 'market',
          timeInForce: 'day',
          idempotencyKey,
          traceId,
        }),
        traceId,
      });

      if (!orderRes.ok) {
        this.log.error(
          { traceId, symbol: trade.symbol, side: trade.side, status: orderRes.status, body: orderRes.body },
          '[runner] order submission failed',
        );
        runnerOrdersSubmittedTotal.inc({ symbol: trade.symbol, side: trade.side, outcome: 'order_failed' });
        return;
      }

      this.log.info(
        { traceId, symbol: trade.symbol, side: trade.side, notional: trade.notional, idempotencyKey },
        '[runner] order submitted',
      );
      runnerOrdersSubmittedTotal.inc({ symbol: trade.symbol, side: trade.side, outcome: 'success' });
    } catch (err) {
      this.log.error({ traceId, symbol: trade.symbol, side: trade.side, err: String(err) }, '[runner] submitTrade error');
      runnerOrdersSubmittedTotal.inc({ symbol: trade.symbol, side: trade.side, outcome: 'downstream_error' });
    }
  }

  // ── HTTP helper with timeout + body parse ─────────────────────────

  private async fetchJson(
    url: string,
    opts: { method?: string; headers?: Record<string, string>; body?: string; traceId: string },
  ): Promise<{ ok: boolean; status: number; body: unknown }> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.fetchTimeoutMs);
    try {
      const res = await fetch(url, {
        method: opts.method ?? 'GET',
        headers: { ...(opts.headers ?? {}), 'x-trace-id': opts.traceId },
        body: opts.body,
        signal: controller.signal,
      });
      let body: unknown = null;
      try { 
        body = await res.json(); 
      } catch (parseErr) { 
        // Warn if a 2xx response has unparseable body — likely a misconfigured
        // reverse proxy returning HTML instead of JSON.
        if (res.ok) {
          this.log.warn(
            { traceId: opts.traceId, url, status: res.status, parseErr: String(parseErr) },
            '[runner] 2xx response with non-JSON body — possible proxy misconfiguration'
          );
        }
      }
      return { ok: res.ok, status: res.status, body };
    } finally {
      clearTimeout(timer);
    }
  }
}

// ── helpers ──────────────────────────────────────────────────────────

function parseSymbols(envVal: string | undefined): string[] {
  return (envVal ?? 'AAPL,MSFT,GOOGL')
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function randomTraceId(): string {
  // x-trace-id is an independent correlation ID, not an OTel trace ID.
  // OTel context propagation is handled by the SDK's auto-instrumentation.
  return randomUUID();
}

function round2(n: number): number {
  // EPSILON nudge avoids binary-float midpoint rounding errors.
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

function parsePositiveInt(raw: string | undefined, fallback: number): number {
  if (raw === undefined) return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function parsePositiveFloat(raw: string | undefined, fallback: number): number {
  if (raw === undefined) return fallback;
  const n = Number.parseFloat(raw);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}
