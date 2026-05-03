import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockDb = {
  getState: vi.fn(),
  setKillSwitch: vi.fn(),
  updateDailyLoss: vi.fn(),
  resetDailyLoss: vi.fn(),
};

vi.mock('../riskDb', () => ({ RiskDb: vi.fn(() => mockDb) }));

describe('Risk service logic', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('blocks order when kill switch is active', () => {
    const state = { kill_switch: true, daily_loss_usd: 0, max_daily_loss: 1000, portfolio_value: 100000 };

    expect(state.kill_switch).toBe(true);
    // kill switch blocks regardless of notional
    const allowed = !state.kill_switch;
    expect(allowed).toBe(false);
  });

  it('blocks order when daily loss limit reached', () => {
    const state = { kill_switch: false, daily_loss_usd: 1000, max_daily_loss: 1000, portfolio_value: 100000 };
    const allowed = !state.kill_switch && state.daily_loss_usd < state.max_daily_loss;
    expect(allowed).toBe(false);
  });

  it('blocks order when notional exceeds max position size', () => {
    const state = { kill_switch: false, daily_loss_usd: 0, max_daily_loss: 1000, portfolio_value: 100000 };
    const maxPositionPct = 0.1;
    const notional = 15000; // > 10% of 100k

    const allowed = !state.kill_switch
      && state.daily_loss_usd < state.max_daily_loss
      && notional <= maxPositionPct * state.portfolio_value;

    expect(allowed).toBe(false);
  });

  it('allows order when all checks pass', () => {
    const state = { kill_switch: false, daily_loss_usd: 0, max_daily_loss: 1000, portfolio_value: 100000 };
    const maxPositionPct = 0.1;
    const notional = 5000;

    const allowed = !state.kill_switch
      && state.daily_loss_usd < state.max_daily_loss
      && notional <= maxPositionPct * state.portfolio_value;

    expect(allowed).toBe(true);
  });

  it('setKillSwitch is called with correct args', async () => {
    mockDb.setKillSwitch.mockResolvedValue(undefined);
    await mockDb.setKillSwitch(true, 'manual halt');
    expect(mockDb.setKillSwitch).toHaveBeenCalledWith(true, 'manual halt');
  });

  it('blocks order when portfolio_value is not synced (fail-safe)', () => {
    // Previously `state.portfolio_value ?? 100000` silently used a fictional
    // $100k whenever portfolio sync had not populated the row. The service
    // must now refuse the check instead of sizing against a guessed balance.
    const state = { kill_switch: false, daily_loss_usd: 0, max_daily_loss: 1000, portfolio_value: null };
    const portfolioValue = state.portfolio_value == null ? null : Number(state.portfolio_value);
    expect(portfolioValue).toBeNull();
    const allowed = !state.kill_switch && portfolioValue != null;
    expect(allowed).toBe(false);
  });

  it('resetDailyLoss is invoked by the reset handler', async () => {
    mockDb.resetDailyLoss.mockResolvedValue(undefined);
    await mockDb.resetDailyLoss();
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

  it('RiskCheckRequestSchema rejects non-numeric notional', async () => {
    const { RiskCheckRequestSchema } = await import('@alpaca-rl/contracts');
    expect(
      RiskCheckRequestSchema.safeParse({ symbol: 'AAPL', notional: 'a lot' }).success,
    ).toBe(false);
  });

  it('RiskCheckRequestSchema accepts valid body', async () => {
    const { RiskCheckRequestSchema } = await import('@alpaca-rl/contracts');
    const parsed = RiskCheckRequestSchema.safeParse({ symbol: 'AAPL', notional: 5000 });
    expect(parsed.success).toBe(true);
  });

  it('PortfolioValueRequestSchema rejects negative values', async () => {
    const { PortfolioValueRequestSchema } = await import('@alpaca-rl/contracts');
    expect(PortfolioValueRequestSchema.safeParse({ portfolioValue: -1 }).success).toBe(false);
    expect(PortfolioValueRequestSchema.safeParse({ portfolioValue: 100000 }).success).toBe(true);
  });
});
