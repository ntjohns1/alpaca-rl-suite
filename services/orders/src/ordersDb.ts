import { Pool } from 'pg';
import { Config } from '@alpaca-rl/config';
import { v4 as uuidv4 } from 'uuid';

export class OrdersDb {
  private pool: Pool;

  constructor(config: Config) {
    this.pool = new Pool({ connectionString: config.DATABASE_URL });
  }

  async createOrder(order: {
    idempotencyKey: string;
    symbol: string;
    side: 'buy' | 'sell';
    qty: number;
    notional?: number;
    orderType: string;
    timeInForce?: string;
    limitPrice?: number;
    traceId?: string;
  }) {
    const id = uuidv4();
    const res = await this.pool.query(
      `INSERT INTO order_event
         (id, idempotency_key, symbol, side, qty, notional, order_type, time_in_force, limit_price, status, trace_id)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'pending',$10)
       ON CONFLICT (idempotency_key) DO UPDATE SET status = order_event.status
       RETURNING *`,
      [
        id, order.idempotencyKey, order.symbol, order.side,
        order.qty, order.notional ?? null, order.orderType,
        order.timeInForce ?? 'day', order.limitPrice ?? null, order.traceId ?? null,
      ],
    );
    return res.rows[0];
  }

  async updateOrderStatus(idempotencyKey: string, update: {
    alpacaOrderId?: string;
    status: string;
    filledQty?: number;
    filledAvgPrice?: number;
    commission?: number;
    rawEvent?: object;
  }) {
    await this.pool.query(
      `UPDATE order_event SET
        alpaca_order_id   = COALESCE($2, alpaca_order_id),
        status            = $3,
        filled_qty        = COALESCE($4, filled_qty),
        filled_avg_price  = COALESCE($5, filled_avg_price),
        commission        = COALESCE($6, commission),
        raw_event         = COALESCE($7, raw_event)
       WHERE idempotency_key = $1`,
      [
        idempotencyKey,
        update.alpacaOrderId ?? null,
        update.status,
        update.filledQty ?? null,
        update.filledAvgPrice ?? null,
        update.commission ?? null,
        update.rawEvent ? JSON.stringify(update.rawEvent) : null,
      ],
    );
  }

  async getOrder(id: string) {
    const res = await this.pool.query(
      `SELECT * FROM order_event WHERE id = $1`, [id],
    );
    return res.rows[0] ?? null;
  }

  async listOrders(status?: string, limit = 100) {
    const params: any[] = [limit];
    const where = status ? `WHERE status = $${params.push(status)}` : '';
    const res = await this.pool.query(
      `SELECT * FROM order_event ${where} ORDER BY created_at DESC LIMIT $1`, params,
    );
    return res.rows;
  }

  async close() {
    await this.pool.end();
  }
}
