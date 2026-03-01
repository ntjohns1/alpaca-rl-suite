import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── fetch mock (hoisted so vi.mock factory can reference it) ─────────
const { mockFetch } = vi.hoisted(() => {
  const mockFetch = vi.fn();
  return { mockFetch };
});

vi.stubGlobal('fetch', mockFetch);

// ── Import after stub ─────────────────────────────────────────────────
import { RunnerScheduler } from '../runnerScheduler';

const mockConfig = {
  RISK_URL:           'http://risk:3005',
  RL_INFER_URL:       'http://rl-infer:8005',
  MARKET_INGEST_URL:  'http://market-ingest:3003',
  FEATURE_BUILDER_URL:'http://feature-builder:8002',
  ORDERS_URL:         'http://orders:3004',
  PORTFOLIO_URL:      'http://portfolio:3006',
  STRATEGY_RUNNER_PORT: 3007,
  MAX_POSITION_SIZE_PCT: 0.1,
} as any;

// ── helpers ──────────────────────────────────────────────────────────

function jsonResp(body: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: () => Promise.resolve(body),
  });
}

function makeBarRows(n = 25) {
  return Array.from({ length: n }, (_, i) => ({ close: (100 + i).toString() }));
}

describe('RunnerScheduler', () => {
  let scheduler: RunnerScheduler;

  beforeEach(() => {
    vi.clearAllMocks();
    process.env.TRADING_SYMBOLS = 'AAPL';
    scheduler = new RunnerScheduler(mockConfig);
  });

  it('start() sets running=true and stop() sets it back to false', () => {
    expect(scheduler.isRunning()).toBe(false);
    scheduler.start();
    expect(scheduler.isRunning()).toBe(true);
    scheduler.stop();
    expect(scheduler.isRunning()).toBe(false);
  });

  it('symbols() returns symbols from env', () => {
    process.env.TRADING_SYMBOLS = 'AAPL,TSLA';
    const s = new RunnerScheduler(mockConfig);
    expect(s.symbols()).toEqual(['AAPL', 'TSLA']);
  });

  it('tick() aborts early when kill switch is active', async () => {
    mockFetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ kill_switch: true }) }); // risk state

    await scheduler.tick();

    // only one fetch call — no infer, no orders
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/risk/state'));
  });

  it('tick() aborts early when risk service is unavailable', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({}) });

    await scheduler.tick();

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('tick() calls infer for each symbol when kill switch is off', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResp({ kill_switch: false }))          // risk state
      .mockResolvedValueOnce(jsonResp(makeBarRows()))                    // bars AAPL
      .mockResolvedValueOnce(jsonResp({ state_vector: Array(10).fill(0.1) })) // features
      .mockResolvedValueOnce(jsonResp({ action: 1, qValues: [0, 1, 0] }))    // infer → HOLD
      .mockResolvedValueOnce(jsonResp({}));                              // portfolio sync

    await scheduler.tick();

    const calls = mockFetch.mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes('/risk/state'))).toBe(true);
    expect(calls.some((u) => u.includes('/infer/action'))).toBe(true);
    expect(calls.some((u) => u.includes('/portfolio/sync'))).toBe(true);
  });

  it('tick() submits buy order for LONG signal after passing risk check', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResp({ kill_switch: false }))                // risk state
      .mockResolvedValueOnce(jsonResp(makeBarRows()))                          // bars
      .mockResolvedValueOnce(jsonResp({ state_vector: Array(10).fill(0.1) })) // features
      .mockResolvedValueOnce(jsonResp({ action: 2, qValues: [0, 0, 1] }))     // infer → LONG
      .mockResolvedValueOnce(jsonResp({}, true))                               // risk check passes
      .mockResolvedValueOnce(jsonResp({ orderId: 'o1' }))                      // orders
      .mockResolvedValueOnce(jsonResp({}));                                    // portfolio sync

    await scheduler.tick();

    const calls = mockFetch.mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u.includes('/risk/check'))).toBe(true);
    expect(calls.some((u) => u.includes('/orders'))).toBe(true);

    const orderCall = mockFetch.mock.calls.find((c) => (c[0] as string).includes('/orders'));
    const orderBody = JSON.parse(orderCall![1].body as string);
    expect(orderBody.side).toBe('buy');
    expect(orderBody.symbol).toBe('AAPL');
  });

  it('tick() blocks order when risk check fails', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResp({ kill_switch: false }))
      .mockResolvedValueOnce(jsonResp(makeBarRows()))
      .mockResolvedValueOnce(jsonResp({ state_vector: Array(10).fill(0.1) }))
      .mockResolvedValueOnce(jsonResp({ action: 2 }))                    // LONG
      .mockResolvedValueOnce(jsonResp({ reason: 'daily loss exceeded' }, false)) // risk BLOCKS
      .mockResolvedValueOnce(jsonResp({}));                               // portfolio sync

    await scheduler.tick();

    const calls = mockFetch.mock.calls.map((c) => c[0] as string);
    // risk/check called but /orders must NOT be called
    expect(calls.some((u) => u.includes('/risk/check'))).toBe(true);
    expect(calls.every((u) => !u.includes('/orders'))).toBe(true);
  });

  it('tick() does not submit order for HOLD signal', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResp({ kill_switch: false }))
      .mockResolvedValueOnce(jsonResp(makeBarRows()))
      .mockResolvedValueOnce(jsonResp({ state_vector: Array(10).fill(0.0) }))
      .mockResolvedValueOnce(jsonResp({ action: 1 }))                    // HOLD
      .mockResolvedValueOnce(jsonResp({}));                               // portfolio sync

    await scheduler.tick();

    const calls = mockFetch.mock.calls.map((c) => c[0] as string);
    expect(calls.every((u) => !u.includes('/orders'))).toBe(true);
    expect(calls.every((u) => !u.includes('/risk/check'))).toBe(true);
  });

  it('tick() submits sell order for SHORT signal after passing risk check', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResp({ kill_switch: false }))
      .mockResolvedValueOnce(jsonResp(makeBarRows()))
      .mockResolvedValueOnce(jsonResp({ state_vector: Array(10).fill(-0.1) }))
      .mockResolvedValueOnce(jsonResp({ action: 0 }))                    // SHORT
      .mockResolvedValueOnce(jsonResp({}, true))                         // risk check passes
      .mockResolvedValueOnce(jsonResp({ orderId: 'o2' }))
      .mockResolvedValueOnce(jsonResp({}));

    await scheduler.tick();

    const orderCall = mockFetch.mock.calls.find((c) => (c[0] as string).includes('/orders'));
    const orderBody = JSON.parse(orderCall![1].body as string);
    expect(orderBody.side).toBe('sell');
  });

  it('tick() falls back to simple returns when feature service unavailable', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResp({ kill_switch: false }))
      .mockResolvedValueOnce(jsonResp(makeBarRows(30)))      // bars
      .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({}) }) // features fail
      .mockResolvedValueOnce(jsonResp({ action: 1 }))        // HOLD
      .mockResolvedValueOnce(jsonResp({}));                   // portfolio sync

    // Should not throw
    await expect(scheduler.tick()).resolves.toBeUndefined();
  });
});
