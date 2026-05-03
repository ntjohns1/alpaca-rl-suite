import Alpaca from '@alpacahq/alpaca-trade-api';
import { Config } from '@alpaca-rl/config';
import { SubmitOrderRequest } from '@alpaca-rl/contracts';

/** Map caller-facing timeframe strings to Alpaca v2 API timeframe values. */
const TIMEFRAME_MAP: Record<string, string> = {
  '1m': '1Min',
  '5m': '5Min',
  '15m': '15Min',
  '30m': '30Min',
  '1h': '1Hour',
  '4h': '4Hour',
  '1d': '1Day',
  '1w': '1Week',
  '1mo': '1Month',
};

export class AlpacaClient {
  private alpaca: InstanceType<typeof Alpaca>;

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
    // SDK types incorrectly mark all params as required; only status/limit are needed
    return this.alpaca.getOrders({ status, limit } as Parameters<typeof this.alpaca.getOrders>[0]);
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
    const tf = TIMEFRAME_MAP[timeframe];
    if (!tf) {
      throw new Error(
        `Unsupported timeframe "${timeframe}". Valid values: ${Object.keys(TIMEFRAME_MAP).join(', ')}`,
      );
    }
    const resp = this.alpaca.getBarsV2(symbol, {
      timeframe: tf,
      start,
      end,
      limit: limit ?? 1000,
      feed: this.config.ALPACA_FEED,
    });
    const bars: any[] = [];
    for await (const bar of resp) {
      bars.push(bar);
    }
    return bars;
  }
}
