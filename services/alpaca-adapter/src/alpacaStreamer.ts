import { Config } from '@alpaca-rl/config';
import { connect, NatsConnection, StringCodec } from 'nats';
import { SUBJECTS, BarEvent } from '@alpaca-rl/contracts';
import { v4 as uuidv4 } from 'uuid';

export class AlpacaStreamer {
  private nc: NatsConnection | null = null;
  private sc = StringCodec();

  constructor(private config: Config) {}

  async connect() {
    this.nc = await connect({ servers: this.config.NATS_URL });
    console.log('AlpacaStreamer: connected to NATS');
  }

  async subscribeToDataStream(symbols: string[]) {
    if (!this.nc) throw new Error('NATS not connected');

    const Alpaca = require('@alpacahq/alpaca-trade-api');
    const alpaca = new Alpaca({
      keyId: this.config.ALPACA_API_KEY,
      secretKey: this.config.ALPACA_API_SECRET,
      paper: this.config.TRADING_MODE === 'paper',
    });

    const stream = alpaca.data_stream_v2;

    stream.onConnect(() => {
      console.log('Alpaca data stream connected');
      stream.subscribeForBars(symbols);
    });

    stream.onBar((bar: any) => {
      const event: BarEvent = {
        traceId: uuidv4(),
        symbol: bar.Symbol,
        time: bar.Timestamp,
        open: bar.OpenPrice,
        high: bar.HighPrice,
        low: bar.LowPrice,
        close: bar.ClosePrice,
        volume: bar.Volume,
        vwap: bar.VWAP,
        tradeCount: bar.TradeCount,
        timeframe: '1m',
      };
      this.nc!.publish(
        `${SUBJECTS.MARKET_BAR_1M}.${bar.Symbol}`,
        this.sc.encode(JSON.stringify(event)),
      );
    });

    stream.onError((err: Error) => {
      console.error('Alpaca stream error:', err.message);
    });

    stream.connect();
  }

  async publishOrderEvent(subject: string, payload: object) {
    if (!this.nc) return;
    this.nc.publish(subject, this.sc.encode(JSON.stringify(payload)));
  }

  async close() {
    await this.nc?.drain();
  }
}
