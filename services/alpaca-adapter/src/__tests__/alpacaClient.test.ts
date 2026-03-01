import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AlpacaClient } from '../alpacaClient';

// Mock the Alpaca SDK
vi.mock('@alpacahq/alpaca-trade-api', () => {
  return {
    default: vi.fn().mockImplementation(() => ({
      createOrder: vi.fn().mockResolvedValue({
        id: 'order-123',
        symbol: 'AAPL',
        side: 'buy',
        qty: '1',
        status: 'accepted',
        order_type: 'market',
        time_in_force: 'day',
        client_order_id: 'idem-key-1',
      }),
      getOrder: vi.fn().mockResolvedValue({ id: 'order-123', status: 'filled' }),
      getOrders: vi.fn().mockResolvedValue([]),
      cancelOrder: vi.fn().mockResolvedValue(undefined),
      getPositions: vi.fn().mockResolvedValue([]),
      getPosition: vi.fn().mockResolvedValue({ symbol: 'AAPL', qty: '1' }),
      getAccount: vi.fn().mockResolvedValue({
        id: 'acc-1',
        equity: '100000',
        cash: '50000',
        portfolio_value: '100000',
      }),
    })),
  };
});

const mockConfig = {
  ALPACA_API_KEY: 'test-key',
  ALPACA_API_SECRET: 'test-secret',
  TRADING_MODE: 'paper' as const,
  ALPACA_BASE_URL: 'https://paper-api.alpaca.markets',
} as any;

describe('AlpacaClient', () => {
  let client: AlpacaClient;

  beforeEach(() => {
    client = new AlpacaClient(mockConfig);
  });

  it('submits a market order', async () => {
    const order = await client.submitOrder({
      symbol: 'AAPL',
      side: 'buy',
      qty: 1,
      orderType: 'market',
      timeInForce: 'day',
      idempotencyKey: 'idem-key-1',
    });
    expect(order.id).toBe('order-123');
    expect(order.symbol).toBe('AAPL');
  });

  it('fetches account info', async () => {
    const account = await client.getAccount();
    expect(account.equity).toBe('100000');
  });

  it('lists positions', async () => {
    const positions = await client.getPositions();
    expect(Array.isArray(positions)).toBe(true);
  });

  it('cancels an order', async () => {
    await expect(client.cancelOrder('order-123')).resolves.toBeUndefined();
  });
});
