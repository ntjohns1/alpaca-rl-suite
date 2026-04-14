import {
  connect,
  NatsConnection,
  StringCodec,
  JetStreamManager,
  JetStreamClient,
  AckPolicy,
  DeliverPolicy,
  RetentionPolicy,
  StorageType,
} from 'nats';
import { Config } from '@alpaca-rl/config';
import { BarEventSchema } from '@alpaca-rl/contracts';
import { DbClient } from './dbClient';

const sc = StringCodec();

export class NatsBarConsumer {
  private nc: NatsConnection | null = null;
  private js: JetStreamClient | null = null;
  private running = false;

  constructor(private config: Config, private db: DbClient) {}

  async connect() {
    this.nc = await connect({ servers: this.config.NATS_URL });
    const jsm: JetStreamManager = await this.nc.jetstreamManager();

    // Ensure the stream exists
    try {
      await jsm.streams.add({
        name: 'MARKET_BARS',
        subjects: ['market.bars.>'],
        retention: RetentionPolicy.Limits,
        storage: StorageType.File,
        max_age: 7 * 24 * 60 * 60 * 1e9, // 7 days in nanoseconds
      });
    } catch {
      // Stream already exists — update subjects if needed
      await jsm.streams.update('MARKET_BARS', {
        subjects: ['market.bars.>'],
        max_age: 7 * 24 * 60 * 60 * 1e9,
      });
    }

    this.js = this.nc.jetstream();
    console.log('[nats-consumer] connected and stream ready');
  }

  async startConsuming() {
    if (!this.js || !this.nc) throw new Error('Not connected');
    this.running = true;

    const consumer = await this.js.consumers.get('MARKET_BARS', 'market-ingest-consumer').catch(
      async () => {
        const jsm = await this.nc!.jetstreamManager();
        await jsm.consumers.add('MARKET_BARS', {
          durable_name: 'market-ingest-consumer',
          ack_policy: AckPolicy.Explicit,
          deliver_policy: DeliverPolicy.New,
          filter_subject: 'market.bars.>',
        });
        return this.js!.consumers.get('MARKET_BARS', 'market-ingest-consumer');
      },
    );

    console.log('[nats-consumer] starting bar consumption');

    const msgs = await consumer.consume({ max_messages: 100 });

    (async () => {
      for await (const msg of msgs) {
        if (!this.running) break;
        try {
          const raw = JSON.parse(sc.decode(msg.data));
          const parsed = BarEventSchema.safeParse(raw);

          if (!parsed.success) {
            console.warn('[nats-consumer] invalid bar event:', parsed.error.issues[0]);
            msg.ack();
            continue;
          }

          const bar = parsed.data;
          const table = bar.timeframe === '1m' ? 'bar_1m' : 'bar_1d';

          await this.db.upsertBar(table, {
            time: bar.time,
            symbol: bar.symbol,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
            volume: bar.volume,
            vwap: bar.vwap,
            tradeCount: bar.tradeCount,
          });

          msg.ack();
        } catch (err) {
          console.error('[nats-consumer] processing error:', err);
          msg.nak();
        }
      }
    })();
  }

  async stop() {
    this.running = false;
    await this.nc?.drain();
  }
}
