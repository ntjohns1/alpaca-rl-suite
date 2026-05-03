import { Config } from '@alpaca-rl/config';
import { SubmitOrderRequest } from '@alpaca-rl/contracts';
import { OrdersDb } from './ordersDb';

const BROKER_TIMEOUT_MS = 10_000;

class BrokerError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BrokerError';
  }
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = BROKER_TIMEOUT_MS) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

export class OrdersService {
  constructor(
    private config: Config,
    private db: OrdersDb,
  ) {}

  /**
   * Order submission flow (idempotent on `idempotencyKey`):
   *   1. Look up by idempotency key — if a finalized record exists, return it
   *      without calling the broker (so retries don't double-submit).
   *   2. Insert (or upsert) a 'pending' row keyed on idempotencyKey.
   *   3. Call alpaca-adapter with a hard timeout. On non-ok or transport
   *      failure, mark the row 'failed' and throw.
   *   4. On success, finalize the row to 'accepted' with the broker's order id.
   *
   * If step 4 fails (DB blip after broker accepted), the row stays 'pending'
   * and Alpaca holds the order. A reconciler is required to sweep stuck
   * 'pending' rows and patch them with the broker's order id; in the meantime
   * Alpaca's own dedupe via `client_order_id = idempotencyKey` (forwarded by
   * alpaca-adapter) prevents a retry from producing a duplicate fill.
   */
  async submitOrder(req: SubmitOrderRequest & { traceId?: string }) {
    // 1. Dedupe on retry. 'failed' is intentionally excluded so a retry with
    // the same key after a broker rejection (e.g. transient insufficient
    // funds) re-submits rather than silently returning the failed record.
    const existing = await this.db.getOrderByIdempotencyKey(req.idempotencyKey);
    if (existing && (existing.status === 'accepted' || existing.status === 'pending')) {
      return {
        ...existing,
        alpacaOrderId: existing.alpaca_order_id ?? undefined,
        status: existing.status,
      };
    }

    // 2. Persist pending row (idempotent: ON CONFLICT (idempotency_key) returns existing).
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

    // 3. Broker call with timeout. Mark 'failed' on any transport-or-status error.
    let alpacaOrder: { id: string; [k: string]: unknown };
    try {
      const res = await fetchWithTimeout(`${this.config.ALPACA_ADAPTER_URL}/alpaca/orders`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-trace-id': req.traceId ?? '' },
        body: JSON.stringify(req),
      });

      if (!res.ok) {
        const err = await res.text();
        await this.db.updateOrderStatus(req.idempotencyKey, { status: 'failed' });
        throw new BrokerError(`Alpaca order failed: ${err}`);
      }

      alpacaOrder = await res.json();
    } catch (err: any) {
      // BrokerError = we already flipped the row to 'failed' above; just rethrow.
      // Anything else = transport failure (network/abort). Try to mark the row
      // 'failed' so it reflects reality; if that itself fails, propagate the
      // original error and let the reconciler sweep the stuck 'pending' row.
      if (err instanceof BrokerError) throw err;
      await this.db.updateOrderStatus(req.idempotencyKey, { status: 'failed' }).catch((dbErr) => {
        console.error(
          { err: dbErr, idempotencyKey: req.idempotencyKey },
          'failed to mark order failed after broker transport error — row stuck pending',
        );
      });
      throw new Error(`Alpaca order request failed: ${err?.message ?? err}`);
    }

    // 4. Finalize.
    await this.db.updateOrderStatus(req.idempotencyKey, {
      alpacaOrderId: alpacaOrder.id,
      status: 'accepted',
      rawEvent: alpacaOrder,
    });

    return { ...record, alpacaOrderId: alpacaOrder.id, status: 'accepted' };
  }

  /**
   * Cancel flow (symmetric to submit):
   *   1. Look up by internal id.
   *   2. Mark 'cancelling' before contacting the broker so a crash mid-flight
   *      leaves a recognizable intermediate state for a reconciler to sweep.
   *      (`order_event.status` is plain TEXT with no CHECK constraint — see
   *      infra/migrations/init.sql — so introducing a new value is safe.)
   *   3. Call alpaca-adapter DELETE with a timeout. On non-ok, attempt to
   *      revert the row back to its prior status and throw.
   *   4. On broker success, finalize to 'cancelled'.
   *
   * Note: `id` is the internal UUID column `order_event.id`, not the Alpaca
   * order id and not the idempotency key.
   */
  async cancelOrder(id: string) {
    const order = await this.db.getOrder(id);
    if (!order) throw new Error('Order not found');

    // Idempotent: already cancelled.
    if (order.status === 'cancelled') return order;

    if (order.alpaca_order_id) {
      const priorStatus = order.status;
      await this.db.updateOrderStatus(order.idempotency_key, { status: 'cancelling' });

      try {
        const res = await fetchWithTimeout(
          `${this.config.ALPACA_ADAPTER_URL}/alpaca/orders/${order.alpaca_order_id}`,
          { method: 'DELETE' },
        );
        if (!res.ok) {
          const err = await res.text();
          // Broker rejected the cancel — restore state so the row doesn't get
          // stuck in 'cancelling'.
          await this.db
            .updateOrderStatus(order.idempotency_key, { status: priorStatus })
            .catch((dbErr) => {
              console.error(
                { err: dbErr, id, priorStatus },
                'failed to revert order status after broker cancel rejection — row stuck cancelling',
              );
            });
          throw new BrokerError(`Alpaca cancel failed: ${err}`);
        }
      } catch (err: any) {
        if (err instanceof BrokerError) throw err;
        await this.db
          .updateOrderStatus(order.idempotency_key, { status: priorStatus })
          .catch((dbErr) => {
            console.error(
              { err: dbErr, id, priorStatus },
              'failed to revert order status after broker cancel transport error — row stuck cancelling',
            );
          });
        throw new Error(`Alpaca cancel request failed: ${err?.message ?? err}`);
      }
    }

    await this.db.updateOrderStatus(order.idempotency_key, { status: 'cancelled' });
    return { ...order, status: 'cancelled' };
  }
}
