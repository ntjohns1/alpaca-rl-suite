import { describe, it, expect, vi, beforeEach } from 'vitest';
import { OrdersService } from '../ordersService';

const mockDb = {
  createOrder: vi.fn(),
  updateOrderStatus: vi.fn(),
  getOrder: vi.fn(),
  getOrderByIdempotencyKey: vi.fn(),
  listOrders: vi.fn(),
};

const mockConfig = {
  ALPACA_ADAPTER_URL: 'http://localhost:3002',
} as any;

const baseRequest = {
  symbol: 'AAPL' as const,
  side: 'buy' as const,
  qty: 1,
  orderType: 'market' as const,
  timeInForce: 'day' as const,
};

describe('OrdersService.submitOrder', () => {
  let svc: OrdersService;

  beforeEach(() => {
    vi.clearAllMocks();
    svc = new OrdersService(mockConfig, mockDb as any);

    mockDb.getOrderByIdempotencyKey.mockResolvedValue(null);
    mockDb.createOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      symbol: 'AAPL',
      side: 'buy',
      status: 'pending',
    });
    mockDb.updateOrderStatus.mockResolvedValue(undefined);
  });

  it('inserts pending row, calls broker, finalizes to accepted', async () => {
    const alpacaResponse = { id: 'alpaca-order-1', status: 'accepted' };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => alpacaResponse,
    } as any);

    const result = await svc.submitOrder({ ...baseRequest, idempotencyKey: 'idem-1' });

    // Order matters: dedupe lookup, then INSERT pending, then broker call, then finalize.
    expect(mockDb.getOrderByIdempotencyKey).toHaveBeenCalledWith('idem-1');
    expect(mockDb.createOrder).toHaveBeenCalledOnce();
    expect(mockDb.updateOrderStatus).toHaveBeenCalledWith('idem-1', {
      alpacaOrderId: 'alpaca-order-1',
      status: 'accepted',
      rawEvent: alpacaResponse,
    });
    expect(result.status).toBe('accepted');
  });

  it('returns existing record without calling broker on idempotent retry', async () => {
    mockDb.getOrderByIdempotencyKey.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      alpaca_order_id: 'alpaca-order-1',
      status: 'accepted',
    });
    global.fetch = vi.fn();

    const result = await svc.submitOrder({ ...baseRequest, idempotencyKey: 'idem-1' });

    expect(global.fetch).not.toHaveBeenCalled();
    expect(mockDb.createOrder).not.toHaveBeenCalled();
    expect(mockDb.updateOrderStatus).not.toHaveBeenCalled();
    expect(result.status).toBe('accepted');
    expect(result.alpacaOrderId).toBe('alpaca-order-1');
  });

  it('marks row failed and throws when adapter returns non-ok', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      text: async () => 'insufficient funds',
    } as any);

    await expect(svc.submitOrder({ ...baseRequest, idempotencyKey: 'idem-2' })).rejects.toThrow(
      'Alpaca order failed',
    );

    expect(mockDb.createOrder).toHaveBeenCalledOnce();
    expect(mockDb.updateOrderStatus).toHaveBeenCalledWith('idem-2', { status: 'failed' });
  });

  it('marks row failed and throws when broker request errors (timeout/network)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED'));

    await expect(svc.submitOrder({ ...baseRequest, idempotencyKey: 'idem-3' })).rejects.toThrow(
      'Alpaca order request failed',
    );

    expect(mockDb.updateOrderStatus).toHaveBeenCalledWith('idem-3', { status: 'failed' });
  });

  it('propagates DB error when finalize update fails (row stays pending — reconciler territory)', async () => {
    // Broker accepted the order but the finalize UPDATE blew up. The row will
    // stay in 'pending' and the broker is holding the order. Caller sees the
    // error so they don't think the order was confirmed.
    const alpacaResponse = { id: 'alpaca-order-1', status: 'accepted' };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => alpacaResponse,
    } as any);
    mockDb.updateOrderStatus.mockRejectedValueOnce(new Error('connection terminated'));

    await expect(svc.submitOrder({ ...baseRequest, idempotencyKey: 'idem-4' })).rejects.toThrow(
      'connection terminated',
    );

    // The pending row was created (step 2). The finalize update was attempted
    // (step 4) and threw. No second updateOrderStatus call.
    expect(mockDb.createOrder).toHaveBeenCalledOnce();
    expect(mockDb.updateOrderStatus).toHaveBeenCalledTimes(1);
    expect(mockDb.updateOrderStatus).toHaveBeenCalledWith(
      'idem-4',
      expect.objectContaining({
        status: 'accepted',
        alpacaOrderId: 'alpaca-order-1',
      }),
    );
  });
});

describe('OrdersService.cancelOrder', () => {
  let svc: OrdersService;

  beforeEach(() => {
    vi.clearAllMocks();
    svc = new OrdersService(mockConfig, mockDb as any);
    mockDb.updateOrderStatus.mockResolvedValue(undefined);
  });

  it('throws when cancelling a non-existent order', async () => {
    mockDb.getOrder.mockResolvedValue(null);
    await expect(svc.cancelOrder('bad-id')).rejects.toThrow('Order not found');
  });

  it('marks cancelling, calls broker, finalizes to cancelled', async () => {
    mockDb.getOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      alpaca_order_id: 'alpaca-order-1',
      status: 'accepted',
    });
    global.fetch = vi.fn().mockResolvedValue({ ok: true } as any);

    await svc.cancelOrder('local-order-1');

    expect(mockDb.updateOrderStatus).toHaveBeenNthCalledWith(1, 'idem-1', { status: 'cancelling' });
    expect(mockDb.updateOrderStatus).toHaveBeenNthCalledWith(2, 'idem-1', { status: 'cancelled' });
  });

  it('reverts to prior status when adapter rejects cancel', async () => {
    mockDb.getOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      alpaca_order_id: 'alpaca-order-1',
      status: 'accepted',
    });
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      text: async () => 'order already filled',
    } as any);

    await expect(svc.cancelOrder('local-order-1')).rejects.toThrow('Alpaca cancel failed');

    expect(mockDb.updateOrderStatus).toHaveBeenNthCalledWith(1, 'idem-1', { status: 'cancelling' });
    expect(mockDb.updateOrderStatus).toHaveBeenNthCalledWith(2, 'idem-1', { status: 'accepted' });
  });

  it('reverts to prior status on broker request error', async () => {
    mockDb.getOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      alpaca_order_id: 'alpaca-order-1',
      status: 'accepted',
    });
    global.fetch = vi.fn().mockRejectedValue(new Error('socket hang up'));

    await expect(svc.cancelOrder('local-order-1')).rejects.toThrow('Alpaca cancel request failed');
    expect(mockDb.updateOrderStatus).toHaveBeenNthCalledWith(2, 'idem-1', { status: 'accepted' });
  });

  it('is a no-op when order is already cancelled', async () => {
    mockDb.getOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      alpaca_order_id: 'alpaca-order-1',
      status: 'cancelled',
    });
    global.fetch = vi.fn();

    const result = await svc.cancelOrder('local-order-1');

    expect(global.fetch).not.toHaveBeenCalled();
    expect(mockDb.updateOrderStatus).not.toHaveBeenCalled();
    expect(result.status).toBe('cancelled');
  });

  it('propagates finalize DB error after broker accepted (row stuck in cancelling)', async () => {
    mockDb.getOrder.mockResolvedValue({
      id: 'local-order-1',
      idempotency_key: 'idem-1',
      alpaca_order_id: 'alpaca-order-1',
      status: 'accepted',
    });
    global.fetch = vi.fn().mockResolvedValue({ ok: true } as any);
    // First call (set cancelling) succeeds, second call (set cancelled) fails.
    mockDb.updateOrderStatus
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('connection terminated'));

    await expect(svc.cancelOrder('local-order-1')).rejects.toThrow('connection terminated');
    // Row left in 'cancelling' for reconciler to sweep.
  });
});
