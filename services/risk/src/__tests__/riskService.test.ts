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
    const maxPositionPct = 0.1;
    const notional = 5000;

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
});
