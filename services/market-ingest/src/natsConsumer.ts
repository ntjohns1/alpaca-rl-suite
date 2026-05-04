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
import type { FastifyBaseLogger } from 'fastify';
import { Config } from '@alpaca-rl/config';
import { BarEventSchema } from '@alpaca-rl/contracts';
import { invalidBarEventsTotal, barProcessingErrorsTotal } from '@alpaca-rl/observability';
import { DbClient } from './dbClient';

const sc = StringCodec();

export class NatsBarConsumer {
  private nc: NatsConnection | null = null;
  private js: JetStreamClient | null = null;
  private running = false;

  constructor(
    private config: Config,
    private db: DbClient,
    private log: FastifyBaseLogger,
  ) {}

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
    this.log.info('[nats-consumer] connected and stream ready');
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

    this.log.info('[nats-consumer] starting bar consumption');

    const msgs = await consumer.consume({ max_messages: 100 });

    // NOTE: Invalid messages are acked (not nak'd) to avoid infinite redelivery.
    // There is currently no dead-letter queue — malformed events are dropped.
    (async () => {
      for await (const msg of msgs) {
        if (!this.running) break;
        // Hoisted so the catch block can label the metric even if parsing succeeded
        // but the DB write failed.
        let symbolForMetric = 'unknown';
        try {
          const raw = JSON.parse(sc.decode(msg.data));
          const parsed = BarEventSchema.safeParse(raw);

          if (!parsed.success) {
            // Best-effort symbol extraction from raw payload for metric label.
            if (typeof raw?.symbol === 'string') symbolForMetric = raw.symbol;
            this.log.warn({ issue: parsed.error.issues[0] }, '[nats-consumer] invalid bar event');
            invalidBarEventsTotal.inc({ symbol: symbolForMetric });
            msg.ack();
            continue;
          }

          const bar = parsed.data;
          symbolForMetric = bar.symbol;
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
          this.log.error({ err, symbol: symbolForMetric }, '[nats-consumer] processing error');
          barProcessingErrorsTotal.inc({ symbol: symbolForMetric });
          msg.nak();
        }
      }
    })().catch((err) => {
      this.running = false;
      this.log.error({ err }, '[nats-consumer] message iterator failed');
    });
  }

  async stop() {
    this.running = false;
    await this.nc?.drain();
  }
}
