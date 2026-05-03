import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import jwt from 'jsonwebtoken';

// ── Mock config ───────────────────────────────────────────────────────────────
const TEST_JWT_SECRET = 'test-secret-that-is-at-least-32-characters';

vi.mock('@alpaca-rl/config', () => ({
  loadConfig: () => ({
    JWT_SECRET: TEST_JWT_SECRET,
    MAX_POSITION_SIZE_PCT: 0.1,
    MAX_PORTFOLIO_STALENESS_S: 3600,
  }),
}));

vi.mock('@alpaca-rl/observability', () => ({
  registry: { contentType: 'text/plain', metrics: async () => '' },
}));

// ── Mock DB ───────────────────────────────────────────────────────────────────
const NOW = Date.now();
const freshState = () => ({
  id: 1,
  kill_switch: false,
  daily_loss_usd: '0',
  max_daily_loss: '1000',
  portfolio_value: '100000',
  portfolio_value_updated_at: new Date(NOW - 60_000).toISOString(), // 1 minute ago — fresh
  reason: null,
});

const mockDb = {
  getState: vi.fn(),
  setKillSwitch: vi.fn(),
  updateDailyLoss: vi.fn(),
  resetDailyLoss: vi.fn(),
  updatePortfolioValue: vi.fn(),
};
vi.mock('../riskDb', () => ({ RiskDb: vi.fn(() => mockDb) }));

// ── Helpers ───────────────────────────────────────────────────────────────────
function makeToken(scope: string) {
  return jwt.sign({ sub: 'test-svc', scope }, TEST_JWT_SECRET, {
    algorithm: 'HS256',
    audience: 'risk',
    expiresIn: '1h',
  });
}

async function getApp() {
  // Dynamic import so the vi.mock calls above are applied first.
  const { createApp } = await import('../app.js');
  return createApp();
}

// ── Tests ─────────────────────────────────────────────────────────────────────
describe('/risk/check route', () => {
  let app: Awaited<ReturnType<typeof getApp>>;

  beforeEach(async () => {
    vi.clearAllMocks();
    app = await getApp();
  });

  afterEach(async () => {
    await app.close();
  });

  it('allows a valid order when all checks pass', async () => {
    mockDb.getState.mockResolvedValue(freshState());
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL', notional: 5000 },
    });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ allowed: true, symbol: 'AAPL' });
  });

  it('returns 403 when kill switch is active', async () => {
    mockDb.getState.mockResolvedValue({ ...freshState(), kill_switch: true });
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL', notional: 5000 },
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toMatchObject({ allowed: false, reason: 'kill_switch_active' });
  });

  it('returns 503 with reason portfolio_unsynced when portfolio_value is null', async () => {
    mockDb.getState.mockResolvedValue({
      ...freshState(),
      portfolio_value: null,
      portfolio_value_updated_at: null,
    });
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL', notional: 5000 },
    });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toMatchObject({ allowed: false, reason: 'portfolio_unsynced' });
  });

  it('returns 503 with reason portfolio_stale when last sync exceeds staleness threshold', async () => {
    // 2 hours ago — exceeds default 3600 s threshold
    const staleTs = new Date(NOW - 2 * 3600 * 1000).toISOString();
    mockDb.getState.mockResolvedValue({
      ...freshState(),
      portfolio_value_updated_at: staleTs,
    });
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL', notional: 5000 },
    });
    expect(res.statusCode).toBe(503);
    expect(res.json()).toMatchObject({ allowed: false, reason: 'portfolio_stale' });
  });

  it('returns 403 when notional exceeds max position size', async () => {
    mockDb.getState.mockResolvedValue(freshState()); // portfolio_value = 100k, limit = 10k
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL', notional: 15000 },
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toMatchObject({ allowed: false });
  });

  it('returns 403 when daily loss limit is reached', async () => {
    mockDb.getState.mockResolvedValue({
      ...freshState(),
      daily_loss_usd: '1000',
      max_daily_loss: '1000',
    });
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL', notional: 5000 },
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toMatchObject({ allowed: false });
  });

  it('returns 400 for invalid body (missing notional)', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL' },
    });
    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for non-positive notional', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/risk/check',
      payload: { symbol: 'AAPL', notional: 0 },
    });
    expect(res.statusCode).toBe(400);
  });
});

describe('/risk/halt and /risk/resume auth', () => {
  let app: Awaited<ReturnType<typeof getApp>>;

  beforeEach(async () => {
    vi.clearAllMocks();
    app = await getApp();
    mockDb.getState.mockResolvedValue(freshState());
    mockDb.setKillSwitch.mockResolvedValue(undefined);
  });

  afterEach(async () => { await app.close(); });

  it('returns 401 with no token', async () => {
    const res = await app.inject({ method: 'POST', url: '/risk/halt', payload: { reason: 'test' } });
    expect(res.statusCode).toBe(401);
  });

  it('returns 403 with wrong scope', async () => {
    const token = makeToken('risk:read');
    const res = await app.inject({
      method: 'POST',
      url: '/risk/halt',
      headers: { authorization: `Bearer ${token}` },
      payload: { reason: 'test' },
    });
    expect(res.statusCode).toBe(403);
  });

  it('activates kill switch with valid token', async () => {
    const token = makeToken('risk:write');
    const res = await app.inject({
      method: 'POST',
      url: '/risk/halt',
      headers: { authorization: `Bearer ${token}` },
      payload: { reason: 'manual test halt' },
    });
    expect(res.statusCode).toBe(200);
    expect(mockDb.setKillSwitch).toHaveBeenCalledWith(true, 'manual test halt');
  });
});

describe('/risk/portfolio auth and staleness', () => {
  let app: Awaited<ReturnType<typeof getApp>>;

  beforeEach(async () => {
    vi.clearAllMocks();
    app = await getApp();
    mockDb.getState.mockResolvedValue(freshState());
    mockDb.updatePortfolioValue.mockResolvedValue(undefined);
  });

  afterEach(async () => { await app.close(); });

  it('returns 401 with no token', async () => {
    const res = await app.inject({ method: 'POST', url: '/risk/portfolio', payload: { portfolioValue: 50000 } });
    expect(res.statusCode).toBe(401);
  });

  it('updates portfolio value with valid token', async () => {
    const token = makeToken('risk:write');
    const res = await app.inject({
      method: 'POST',
      url: '/risk/portfolio',
      headers: { authorization: `Bearer ${token}` },
      payload: { portfolioValue: 50000 },
    });
    expect(res.statusCode).toBe(200);
    expect(mockDb.updatePortfolioValue).toHaveBeenCalledWith(50000);
  });

  it('returns 400 for zero portfolio value', async () => {
    const token = makeToken('risk:write');
    const res = await app.inject({
      method: 'POST',
      url: '/risk/portfolio',
      headers: { authorization: `Bearer ${token}` },
      payload: { portfolioValue: 0 },
    });
    expect(res.statusCode).toBe(400);
  });

  it('returns 400 for negative portfolio value', async () => {
    const token = makeToken('risk:write');
    const res = await app.inject({
      method: 'POST',
      url: '/risk/portfolio',
      headers: { authorization: `Bearer ${token}` },
      payload: { portfolioValue: -1 },
    });
    expect(res.statusCode).toBe(400);
  });
});

describe('/risk/reset-daily-loss auth', () => {
  let app: Awaited<ReturnType<typeof getApp>>;

  beforeEach(async () => {
    vi.clearAllMocks();
    app = await getApp();
    mockDb.getState.mockResolvedValue(freshState());
    mockDb.resetDailyLoss.mockResolvedValue(undefined);
  });

  afterEach(async () => { await app.close(); });

  it('returns 401 with no token', async () => {
    const res = await app.inject({ method: 'POST', url: '/risk/reset-daily-loss' });
    expect(res.statusCode).toBe(401);
  });

  it('resets daily loss with valid token', async () => {
    const token = makeToken('risk:write');
    const res = await app.inject({
      method: 'POST',
      url: '/risk/reset-daily-loss',
      headers: { authorization: `Bearer ${token}` },
    });
    expect(res.statusCode).toBe(200);
    expect(mockDb.resetDailyLoss).toHaveBeenCalledOnce();
  });
});

describe('Risk request schema validation', () => {
  it('RiskCheckRequestSchema rejects missing fields', async () => {
    const { RiskCheckRequestSchema } = await import('@alpaca-rl/contracts');
    expect(RiskCheckRequestSchema.safeParse({}).success).toBe(false);
    expect(RiskCheckRequestSchema.safeParse({ symbol: 'AAPL' }).success).toBe(false);
    expect(RiskCheckRequestSchema.safeParse({ notional: 100 }).success).toBe(false);
  });

  it('RiskCheckRequestSchema rejects non-positive notional', async () => {
    const { RiskCheckRequestSchema } = await import('@alpaca-rl/contracts');
    expect(RiskCheckRequestSchema.safeParse({ symbol: 'AAPL', notional: 0 }).success).toBe(false);
    expect(RiskCheckRequestSchema.safeParse({ symbol: 'AAPL', notional: -100 }).success).toBe(false);
    expect(RiskCheckRequestSchema.safeParse({ symbol: 'AAPL', notional: 'a lot' }).success).toBe(false);
  });

  it('RiskCheckRequestSchema accepts valid positive notional', async () => {
    const { RiskCheckRequestSchema } = await import('@alpaca-rl/contracts');
    expect(RiskCheckRequestSchema.safeParse({ symbol: 'AAPL', notional: 5000 }).success).toBe(true);
  });

  it('PortfolioValueRequestSchema rejects zero and negative values', async () => {
    const { PortfolioValueRequestSchema } = await import('@alpaca-rl/contracts');
    expect(PortfolioValueRequestSchema.safeParse({ portfolioValue: 0 }).success).toBe(false);
    expect(PortfolioValueRequestSchema.safeParse({ portfolioValue: -1 }).success).toBe(false);
    expect(PortfolioValueRequestSchema.safeParse({ portfolioValue: 100000 }).success).toBe(true);
  });
});
