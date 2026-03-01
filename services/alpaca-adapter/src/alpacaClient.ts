import Alpaca from '@alpacahq/alpaca-trade-api';
import { Config } from '@alpaca-rl/config';
import { SubmitOrderRequest } from '@alpaca-rl/contracts';

export class AlpacaClient {
  private alpaca: any;

  constructor(private config: Config) {
    this.alpaca = new Alpaca({
      keyId: config.ALPACA_API_KEY,
      secretKey: config.ALPACA_API_SECRET,
      paper: config.TRADING_MODE === 'paper',
      baseUrl: config.ALPACA_BASE_URL,
    });
  }

  async submitOrder(req: SubmitOrderRequest) {
    return this.alpaca.createOrder({
      symbol: req.symbol,
      side: req.side,
      type: req.orderType,
      time_in_force: req.timeInForce,
      ...(req.qty !== undefined ? { qty: String(req.qty) } : {}),
      ...(req.notional !== undefined ? { notional: String(req.notional) } : {}),
      ...(req.limitPrice !== undefined ? { limit_price: String(req.limitPrice) } : {}),
      client_order_id: req.idempotencyKey,
    });
  }

  async getOrder(orderId: string) {
    return this.alpaca.getOrder(orderId);
  }

  async listOrders(status = 'all', limit = 500) {
    return this.alpaca.getOrders({ status, limit });
  }

  async cancelOrder(orderId: string) {
    return this.alpaca.cancelOrder(orderId);
  }

  async getPositions() {
    return this.alpaca.getPositions();
  }

  async getPosition(symbol: string) {
    return this.alpaca.getPosition(symbol);
  }

  async getAccount() {
    return this.alpaca.getAccount();
  }

  async getBars(
    symbol: string,
    timeframe: string,
    start?: string,
    end?: string,
    limit?: number,
  ) {
    const tf = timeframe === '1m' ? '1Min' : '1Day';
    const resp = this.alpaca.getBarsV2(symbol, {
      timeframe: tf,
      start,
      end,
      limit: limit ?? 1000,
      feed: 'iex',
    });
    const bars: any[] = [];
    for await (const bar of resp) {
      bars.push(bar);
    }
    return bars;
  }
}
