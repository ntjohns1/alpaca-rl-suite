import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { PortfolioSyncCron } from '../portfolioSync.js';

// ── Mock config ───────────────────────────────────────────────────────────────
vi.mock('@alpaca-rl/config', async () => {
  const real = await vi.importActual<typeof import('@alpaca-rl/config')>('@alpaca-rl/config');
  return {
    ...real,
    loadConfig: () =>
      real.ConfigSchema.parse({
        ALPACA_API_KEY:    'test-key',
        ALPACA_API_SECRET: 'test-secret',
        DATABASE_URL:      'postgres://localhost/test',
        JWT_SECRET:        'test-secret-that-is-at-least-32-characters',
      }),
  };
});

// ── Mock DB ───────────────────────────────────────────────────────────────────
const mockUpdatePortfolioValue = vi.fn();
vi.mock('../riskDb.js', () => ({
  RiskDb: vi.fn(() => ({ updatePortfolioValue: mockUpdatePortfolioValue })),
}));

// ── Mock logger ───────────────────────────────────────────────────────────────
const mockLog = { info: vi.fn(), warn: vi.fn(), error: vi.fn() };

// ── Helpers ───────────────────────────────────────────────────────────────────
function fakeResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as unknown as Response;
}

function freshAccount(portfolioValue = '75000', ageMs = 30_000) {
  return {
    portfolio_value: portfolioValue,
    equity:          portfolioValue,
    created_at:      new Date(Date.now() - ageMs).toISOString(),
  };
}

async function makeCron(): Promise<PortfolioSyncCron> {
  const { PortfolioSyncCron } = await import('../portfolioSync.js');
  const { loadConfig }        = await import('@alpaca-rl/config');
  return new PortfolioSyncCron(
    loadConfig(),
    { updatePortfolioValue: mockUpdatePortfolioValue } as any,
    mockLog,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────
describe('PortfolioSyncCron.run()', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    mockUpdatePortfolioValue.mockResolvedValue({ prior: null });
  });

  it('skips update and warns when portfolio/account returns null (no rows yet)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse(null)));
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).not.toHaveBeenCalled();
    expect(mockLog.warn).toHaveBeenCalled();
  });

  it('skips update and warns when portfolio/account returns non-ok status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse(null, false, 503)));
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).not.toHaveBeenCalled();
    expect(mockLog.warn).toHaveBeenCalled();
  });

  it('skips update and warns when portfolio_value is not a valid number', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      fakeResponse({ portfolio_value: 'garbage', created_at: new Date().toISOString() }),
    ));
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).not.toHaveBeenCalled();
    expect(mockLog.warn).toHaveBeenCalled();
  });

  it('skips update and warns when portfolio_value is zero or negative', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      fakeResponse({ portfolio_value: '0', created_at: new Date().toISOString() }),
    ));
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).not.toHaveBeenCalled();
    expect(mockLog.warn).toHaveBeenCalled();
  });

  it('skips update and warns when upstream snapshot is older than staleness threshold', async () => {
    // Default MAX_PORTFOLIO_STALENESS_S = 3600; use 2-hour-old snapshot.
    const staleTs = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      fakeResponse({ portfolio_value: '50000', created_at: staleTs }),
    ));
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).not.toHaveBeenCalled();
    expect(mockLog.warn).toHaveBeenCalled();
  });

  it('updates portfolio_value with upstream created_at as asOf when data is fresh', async () => {
    // Pin created_at to a known timestamp so the assertion can prove the cron
    // parsed it rather than substituting new Date() (which would also pass
    // the weaker "> 0" check).
    const knownCreatedAt = new Date(Date.now() - 30_000);
    const account = {
      portfolio_value: '75000',
      equity:          '75000',
      created_at:      knownCreatedAt.toISOString(),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse(account)));
    mockUpdatePortfolioValue.mockResolvedValue({ prior: 50000 });
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).toHaveBeenCalledOnce();
    const [value, asOf] = mockUpdatePortfolioValue.mock.calls[0] as [number, Date];
    expect(value).toBe(75000);
    expect(asOf).toBeInstanceOf(Date);
    // Must be exactly the upstream created_at, not wall-clock time.
    expect(asOf.getTime()).toBe(knownCreatedAt.getTime());
    expect(mockLog.info).toHaveBeenCalled();
  });

  it('logs prior=null on first-ever sync without crashing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse(freshAccount())));
    mockUpdatePortfolioValue.mockResolvedValue({ prior: null });
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).toHaveBeenCalledOnce();
    // The info log should include prior: null without throwing.
    const infoCall = mockLog.info.mock.calls[0] as [Record<string, unknown>, string];
    expect(infoCall[0]).toMatchObject({ prior: null, next: 75000 });
  });

  it('re-entrancy guard: second run while first is in flight is skipped', async () => {
    let resolveFirstFetch!: (v: Response) => void;
    const firstFetch = new Promise<Response>((r) => { resolveFirstFetch = r; });
    vi.stubGlobal('fetch', vi.fn()
      .mockReturnValueOnce(firstFetch)              // first call hangs
      .mockResolvedValue(fakeResponse(freshAccount())), // never reached in this test
    );

    const cron = await makeCron();

    // Kick off first run — suspends at `await fetch(...)`.
    const firstRun = cron.run();

    // Second run should see inFlight=true and bail immediately.
    await cron.run();
    expect(mockLog.warn).toHaveBeenCalledWith(
      expect.stringContaining('in flight'),
    );
    expect(mockUpdatePortfolioValue).not.toHaveBeenCalled();

    // Resolve the hanging fetch so the first run can finish cleanly.
    resolveFirstFetch(fakeResponse(null, false, 503));
    await firstRun;
  });

  it('skips update and warns when fetch throws (e.g. network error)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));
    const cron = await makeCron();
    await cron.run();
    expect(mockUpdatePortfolioValue).not.toHaveBeenCalled();
    expect(mockLog.warn).toHaveBeenCalled();
  });
});
