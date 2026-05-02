import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Config } from '@alpaca-rl/config';

// ── fetch mock (hoisted so vi.mock factory can reference it) ─────────
const { mockFetch } = vi.hoisted(() => ({ mockFetch: vi.fn() }));
vi.stubGlobal('fetch', mockFetch);

// ── Import after stub ─────────────────────────────────────────────────
import { RunnerScheduler } from '../runnerScheduler';

const mockConfig: Config = {
  RISK_URL:           'http://risk:3006',
  RL_INFER_URL:       'http://rl-infer:8005',
  MARKET_INGEST_URL:  'http://market-ingest:3003',
  FEATURE_BUILDER_URL:'http://feature-builder:8002',
  ORDERS_URL:         'http://orders:3005',
  PORTFOLIO_URL:      'http://portfolio:3004',
  STRATEGY_RUNNER_PORT: 3007,
  MAX_POSITION_SIZE_PCT: 0.1,
} as unknown as Config;

const silentLogger = { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} };

// ── helpers ──────────────────────────────────────────────────────────

function jsonResp(body: unknown, ok = true, status = ok ? 200 : 400) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  });
}

/**
 * URL-keyed mock dispatcher. Match each request by URL substring; default
 * responses cover the happy path so tests only need to override what they care
 * about. Robust to call-order changes — the old chained mockResolvedValueOnce
 * approach broke whenever fetch order shifted.
 */
type RouteKey =
  | 'risk/state'
  | 'risk/check'
  | 'portfolio/account'
  | 'portfolio/positions'
  | 'portfolio/sync'
  | 'features/latest'
  | 'infer/action'
  | 'orders';

interface RouteResponses {
  [k: string]: { body: unknown; ok?: boolean; status?: number } | undefined;
}

function installRoutes(overrides: Partial<Record<RouteKey, { body: unknown; ok?: boolean; status?: number }>> = {}) {
  const defaults: RouteResponses = {
    'risk/state':         { body: { kill_switch: false } },
    'risk/check':         { body: { ok: true } },
    'portfolio/account':  { body: { equity: '100000' } },
    'portfolio/positions':{ body: [] },
    'portfolio/sync':     { body: { ok: true } },
    'features/latest':    { body: { state_vector: Array(10).fill(0.1) } },
    'infer/action':       { body: { action: 1 } },
    'orders':             { body: { orderId: 'o1' } },
  };
  const routes = { ...defaults, ...overrides };

  mockFetch.mockImplementation((url: string) => {
    const key = (Object.keys(routes) as RouteKey[]).find((k) => url.includes(k));
    const r = key ? routes[key] : undefined;
    if (!r) return jsonResp({}, true);
    return jsonResp(r.body, r.ok ?? true, r.status ?? (r.ok === false ? 400 : 200));
  });
}

function findCalls(substr: string): Array<[string, RequestInit?]> {
  return mockFetch.mock.calls.filter((c) => (c[0] as string).includes(substr)) as any;
}

// ── tests ────────────────────────────────────────────────────────────

describe('RunnerScheduler', () => {
  let scheduler: RunnerScheduler;

  beforeEach(() => {
    vi.clearAllMocks();
    process.env.TRADING_SYMBOLS = 'AAPL';
    delete process.env.TICK_INTERVAL_MS;
    delete process.env.RUNNER_FETCH_TIMEOUT_MS;
    scheduler = new RunnerScheduler(mockConfig, silentLogger);
  });

  it('start() / stop() flip running flag', async () => {
    expect(scheduler.isRunning()).toBe(false);
    scheduler.start();
    expect(scheduler.isRunning()).toBe(true);
    await scheduler.stop();
    expect(scheduler.isRunning()).toBe(false);
  });

  it('symbols() trims whitespace from env', () => {
    process.env.TRADING_SYMBOLS = 'AAPL, MSFT , GOOGL';
    const s = new RunnerScheduler(mockConfig, silentLogger);
    expect(s.symbols()).toEqual(['AAPL', 'MSFT', 'GOOGL']);
  });

  it('aborts when kill switch is on', async () => {
    installRoutes({ 'risk/state': { body: { kill_switch: true } } });
    await scheduler.tick();
    expect(findCalls('infer/action')).toHaveLength(0);
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('aborts (fail-closed) when risk service is unavailable', async () => {
    installRoutes({ 'risk/state': { body: {}, ok: false, status: 503 } });
    await scheduler.tick();
    expect(findCalls('infer/action')).toHaveLength(0);
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('aborts (fail-closed) when risk-state body is malformed (no kill_switch field)', async () => {
    installRoutes({ 'risk/state': { body: { ok: true } } }); // missing kill_switch
    await scheduler.tick();
    expect(findCalls('infer/action')).toHaveLength(0);
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('aborts (fail-closed) when kill_switch is non-boolean', async () => {
    installRoutes({ 'risk/state': { body: { kill_switch: 'false' } } });
    await scheduler.tick();
    expect(findCalls('infer/action')).toHaveLength(0);
  });

  it('skips tick when equity is unknown', async () => {
    installRoutes({ 'portfolio/account': { body: {}, ok: false, status: 500 } });
    await scheduler.tick();
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('skips tick when positions are unknown (HTTP error) — no over-trading on portfolio outage', async () => {
    installRoutes({
      'portfolio/positions': { body: {}, ok: false, status: 503 },
      'infer/action': { body: { action: 2 } }, // would otherwise buy
    });
    await scheduler.tick();
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('skips tick when positions response is malformed', async () => {
    installRoutes({
      'portfolio/positions': { body: { not: 'an array' } },
      'infer/action': { body: { action: 2 } },
    });
    await scheduler.tick();
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('LONG signal with no current position → buy at full target notional', async () => {
    installRoutes({ 'infer/action': { body: { action: 2 } } });
    await scheduler.tick();
    const orderCalls = findCalls('orders');
    expect(orderCalls).toHaveLength(1);
    const body = JSON.parse(orderCalls[0][1]!.body as string);
    expect(body.side).toBe('buy');
    expect(body.symbol).toBe('AAPL');
    expect(body.notional).toBe(10000); // 100k * 0.1
  });

  it('LONG signal with existing position equal to target → no order (delta ≈ 0)', async () => {
    installRoutes({
      'portfolio/positions': { body: [{ symbol: 'AAPL', market_value: 10000 }] },
      'infer/action':        { body: { action: 2 } },
    });
    await scheduler.tick();
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('LONG signal with partial position → buys only the delta', async () => {
    installRoutes({
      'portfolio/positions': { body: [{ symbol: 'AAPL', market_value: 4000 }] },
      'infer/action':        { body: { action: 2 } },
    });
    await scheduler.tick();
    const orderCalls = findCalls('orders');
    expect(orderCalls).toHaveLength(1);
    const body = JSON.parse(orderCalls[0][1]!.body as string);
    expect(body.notional).toBe(6000);
  });

  it('SHORT signal with no position → no order (we do not open margin shorts)', async () => {
    installRoutes({ 'infer/action': { body: { action: 0 } } });
    await scheduler.tick();
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('SHORT signal with existing long position → sell to close it', async () => {
    installRoutes({
      'portfolio/positions': { body: [{ symbol: 'AAPL', market_value: 7500 }] },
      'infer/action':        { body: { action: 0 } },
    });
    await scheduler.tick();
    const orderCalls = findCalls('orders');
    expect(orderCalls).toHaveLength(1);
    const body = JSON.parse(orderCalls[0][1]!.body as string);
    expect(body.side).toBe('sell');
    expect(body.notional).toBe(7500);
  });

  it('HOLD signal → no risk-check, no order', async () => {
    installRoutes({ 'infer/action': { body: { action: 1 } } });
    await scheduler.tick();
    expect(findCalls('risk/check')).toHaveLength(0);
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('blocks order when risk/check rejects', async () => {
    installRoutes({
      'infer/action': { body: { action: 2 } },
      'risk/check':   { body: { reason: 'daily loss exceeded' }, ok: false, status: 403 },
    });
    await scheduler.tick();
    expect(findCalls('risk/check')).toHaveLength(1);
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('idempotency key is deterministic given the same trace', async () => {
    installRoutes({ 'infer/action': { body: { action: 2 } } });
    await scheduler.tick();
    const orderCalls = findCalls('orders');
    expect(orderCalls).toHaveLength(1);
    const body = JSON.parse(orderCalls[0][1]!.body as string);
    // {traceId}-{symbol}-{side}
    expect(body.idempotencyKey).toMatch(/^.+-AAPL-buy$/);
    expect(body.idempotencyKey.endsWith(`-${body.symbol}-${body.side}`)).toBe(true);
  });

  it('infer with malformed action → no order, no throw', async () => {
    installRoutes({ 'infer/action': { body: { action: 7 } } });
    await expect(scheduler.tick()).resolves.toEqual({ executed: true });
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('feature service unavailable → symbol skipped, no infer call, no order', async () => {
    installRoutes({
      'features/latest': { body: {}, ok: false, status: 503 },
      'infer/action':    { body: { action: 2 } }, // would otherwise trigger order
    });
    await scheduler.tick();
    expect(findCalls('infer/action')).toHaveLength(0);
    expect(findCalls('orders')).toHaveLength(0);
  });

  it('orders endpoint returning 500 → logged, no throw, no success metric', async () => {
    installRoutes({
      'infer/action': { body: { action: 2 } },
      'orders':       { body: { error: 'broker down' }, ok: false, status: 500 },
    });
    await expect(scheduler.tick()).resolves.toEqual({ executed: true });
    expect(findCalls('orders')).toHaveLength(1);
  });

  it('overlapping tick is skipped while previous is in flight, and reports executed=false', async () => {
    let resolveRisk: (v: any) => void = () => {};
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('risk/state')) {
        return new Promise((r) => { resolveRisk = r; });
      }
      return jsonResp({ ok: true });
    });

    const first = scheduler.tick();
    const second = await scheduler.tick();
    expect(second.executed).toBe(false);
    expect(second.reason).toBe('overlap');
    expect(findCalls('risk/state')).toHaveLength(1);

    resolveRisk({ ok: true, status: 200, json: () => Promise.resolve({ kill_switch: true }) });
    const firstResult = await first;
    expect(firstResult.executed).toBe(true);
  });

  it('fetch timeout aborts cleanly without throwing through tick()', async () => {
    process.env.RUNNER_FETCH_TIMEOUT_MS = '20';
    const s = new RunnerScheduler(mockConfig, silentLogger);
    mockFetch.mockImplementation((_url: string, init?: RequestInit) => {
      // Return a never-resolving response; rely on AbortController to fire.
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });
    });
    await expect(s.tick()).resolves.toEqual({ executed: true });
  });
});
