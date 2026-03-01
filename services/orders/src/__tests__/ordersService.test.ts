import { describe, it, expect, vi, beforeEach } from 'vitest';
import { OrdersService } from '../ordersService';

const mockDb = {
  createOrder: vi.fn(),
  updateOrderStatus: vi.fn(),
  getOrder: vi.fn(),
  listOrders: vi.fn(),
};

const mockConfig = {
  ALPACA_ADAPTER_URL: 'http://localhost:3002',
} as any;

describe('OrdersService', () => {
  let svc: OrdersService;

  beforeEach(() => {
    vi.clearAllMocks();
    svc = new OrdersService(mockConfig, mockDb as any);

    mockDb.createOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      symbol: 'AAPL',
      side: 'buy',
      status: 'pending',
    });

    mockDb.updateOrderStatus.mockResolvedValue(undefined);
  });

  it('submits an order and updates status to accepted', async () => {
    const alpacaResponse = { id: 'alpaca-order-1', status: 'accepted' };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => alpacaResponse,
    } as any);

    const result = await svc.submitOrder({
      symbol: 'AAPL',
      side: 'buy',
      qty: 1,
      orderType: 'market',
      timeInForce: 'day',
      idempotencyKey: 'idem-1',
    });

    expect(mockDb.createOrder).toHaveBeenCalledOnce();
    expect(mockDb.updateOrderStatus).toHaveBeenCalledWith('idem-1', {
      alpacaOrderId: 'alpaca-order-1',
      status: 'accepted',
      rawEvent: alpacaResponse,
    });
    expect(result.status).toBe('accepted');
  });

  it('marks order as failed when adapter returns non-ok', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      text: async () => 'insufficient funds',
    } as any);

    await expect(
      svc.submitOrder({
        symbol: 'AAPL',
        side: 'buy',
        qty: 1,
        orderType: 'market',
        timeInForce: 'day',
        idempotencyKey: 'idem-2',
      }),
    ).rejects.toThrow('Alpaca order failed');

    expect(mockDb.updateOrderStatus).toHaveBeenCalledWith('idem-2', { status: 'failed' });
  });

  it('cancels an order via adapter', async () => {
    mockDb.getOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      alpaca_order_id: 'alpaca-order-1',
    });

    global.fetch = vi.fn().mockResolvedValue({ ok: true } as any);

    await svc.cancelOrder('local-order-1');
    expect(mockDb.updateOrderStatus).toHaveBeenCalledWith('idem-1', { status: 'cancelled' });
  });

  it('throws when cancelling a non-existent order', async () => {
    mockDb.getOrder.mockResolvedValue(null);
    await expect(svc.cancelOrder('bad-id')).rejects.toThrow('Order not found');
  });
});
