import { Config } from '@alpaca-rl/config';
import { SubmitOrderRequest } from '@alpaca-rl/contracts';
import { OrdersDb } from './ordersDb';

export class OrdersService {
  constructor(private config: Config, private db: OrdersDb) {}

  async submitOrder(req: SubmitOrderRequest & { traceId?: string }) {
    // Persist order record (idempotent)
    const record = await this.db.createOrder({
      idempotencyKey: req.idempotencyKey,
      symbol: req.symbol,
      side: req.side,
      qty: req.qty ?? 0,
      notional: req.notional,
      orderType: req.orderType,
      timeInForce: req.timeInForce,
      limitPrice: req.limitPrice,
      traceId: req.traceId,
    });

    // Forward to alpaca-adapter
    const res = await fetch(`${this.config.ALPACA_ADAPTER_URL}/alpaca/orders`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-trace-id': req.traceId ?? '' },
      body: JSON.stringify(req),
    });

    if (!res.ok) {
      const err = await res.text();
      await this.db.updateOrderStatus(req.idempotencyKey, { status: 'failed' });
      throw new Error(`Alpaca order failed: ${err}`);
    }

    const alpacaOrder = await res.json();
    await this.db.updateOrderStatus(req.idempotencyKey, {
      alpacaOrderId: alpacaOrder.id,
      status: 'accepted',
      rawEvent: alpacaOrder,
    });

    return { ...record, alpacaOrderId: alpacaOrder.id, status: 'accepted' };
  }

  async cancelOrder(id: string) {
    const order = await this.db.getOrder(id);
    if (!order) throw new Error('Order not found');

    if (order.alpaca_order_id) {
      await fetch(`${this.config.ALPACA_ADAPTER_URL}/alpaca/orders/${order.alpaca_order_id}`, {
        method: 'DELETE',
      });
    }
    await this.db.updateOrderStatus(order.idempotency_key, { status: 'cancelled' });
  }
}
