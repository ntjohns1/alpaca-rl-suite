import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AlpacaClient } from '../alpacaClient';

// Hoisted so the mock factory (also hoisted) can reference it
const { mockGetBarsV2 } = vi.hoisted(() => ({
  mockGetBarsV2: vi.fn(),
}));

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
      getBarsV2: mockGetBarsV2,
    })),
  };
});

const mockConfig = {
  ALPACA_API_KEY: 'test-key',
  ALPACA_API_SECRET: 'test-secret',
  TRADING_MODE: 'paper' as const,
  ALPACA_BASE_URL: 'https://paper-api.alpaca.markets',
  ALPACA_FEED: 'iex' as const,
} as any;

describe('AlpacaClient', () => {
  let client: AlpacaClient;

  beforeEach(() => {
    mockGetBarsV2.mockReset().mockImplementation(() => ({
      async *[Symbol.asyncIterator]() {
        yield { Timestamp: '2024-01-01T00:00:00Z', OpenPrice: 100, HighPrice: 105, LowPrice: 99, ClosePrice: 103, Volume: 1000 };
      },
    }));
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

  it('getBars maps 1m to 1Min', async () => {
    const bars = await client.getBars('AAPL', '1m');
    expect(bars).toHaveLength(1);
    expect(mockGetBarsV2).toHaveBeenCalledWith(
      'AAPL',
      expect.objectContaining({ timeframe: '1Min' }),
    );
  });

  it('getBars maps 1d to 1Day', async () => {
    const bars = await client.getBars('AAPL', '1d');
    expect(bars).toHaveLength(1);
    expect(mockGetBarsV2).toHaveBeenCalledWith(
      'AAPL',
      expect.objectContaining({ timeframe: '1Day' }),
    );
  });

  it('getBars throws on unsupported timeframe', async () => {
    await expect(client.getBars('AAPL', '2m')).rejects.toThrow('Unsupported timeframe "2m"');
    expect(mockGetBarsV2).not.toHaveBeenCalled();
  });

  it('getBars forwards configured feed', async () => {
    await client.getBars('AAPL', '1m');
    expect(mockGetBarsV2).toHaveBeenCalledWith(
      'AAPL',
      expect.objectContaining({ feed: 'iex' }),
    );
  });
});
