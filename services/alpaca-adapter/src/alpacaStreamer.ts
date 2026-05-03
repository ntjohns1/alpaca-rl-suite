import { Config } from '@alpaca-rl/config';
import { connect, NatsConnection, StringCodec } from 'nats';
import { SUBJECTS, BarEventSchema } from '@alpaca-rl/contracts';
import { registry } from '@alpaca-rl/observability';
import { v4 as uuidv4 } from 'uuid';
import client from 'prom-client';
import AlpacaSDK from '@alpacahq/alpaca-trade-api';

// ── Alpaca SDK types ────────────────────────────────────────────────

/** Bar payload pushed by Alpaca's data_stream_v2. */
export interface AlpacaStreamBar {
  Symbol: string;
  Timestamp: string;
  OpenPrice: number;
  HighPrice: number;
  LowPrice: number;
  ClosePrice: number;
  Volume: number;
  VWAP?: number;
  TradeCount?: number;
}

/** Typed surface of data_stream_v2 that we actually use. */
export interface AlpacaDataStream {
  onConnect(cb: () => void): void;
  onBar(cb: (bar: AlpacaStreamBar) => void): void;
  onDisconnect(cb: () => void): void;
  onError(cb: (err: Error) => void): void;
  subscribeForBars(symbols: string[]): void;
  connect(): void;
  disconnect(): void;
}

const AlpacaAPI = AlpacaSDK as unknown as new (
  opts: ConstructorParameters<typeof AlpacaSDK>[0],
) => InstanceType<typeof AlpacaSDK> & { data_stream_v2: AlpacaDataStream };

// ── Constants ───────────────────────────────────────────────────────

const NATS_MAX_RECONNECT_ATTEMPTS = 10;
const NATS_RECONNECT_WAIT_MS = 2_000;
const WS_INITIAL_RETRY_MS = 1_000;
const WS_MAX_RETRY_MS = 30_000;
const WS_MAX_RECONNECT_ATTEMPTS = 10;
const STREAM_TIMEFRAME = '1m' as const;

// ── Metrics ─────────────────────────────────────────────────────────

const barsDroppedTotal: client.Counter<'reason'> =
  (registry.getSingleMetric('alpaca_rl_bars_dropped_total') as client.Counter<'reason'>) ??
  new client.Counter({
    name: 'alpaca_rl_bars_dropped_total',
    help: 'Bars dropped because NATS was unavailable or bar payload was invalid',
    labelNames: ['reason'] as const,
    registers: [registry],
  });

// ── Streamer ────────────────────────────────────────────────────────

export class AlpacaStreamer {
  private nc: NatsConnection | null = null;
  private sc = StringCodec();
  private streamSymbols: string[] = [];

  private alpacaInstance: (InstanceType<typeof AlpacaSDK> & { data_stream_v2: AlpacaDataStream }) | null = null;
  private stream: AlpacaDataStream | null = null;

  private wsRetryMs = WS_INITIAL_RETRY_MS;
  private wsRetryCount = 0;
  private _streamingConfigured = false;
  private _streamingHealthy = false;
  private _streamingDead = false;
  private natsMonitor: Promise<void> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(private config: Config) {}

  /** Whether subscribeToDataStream has been called (streaming is intended). */
  get streamingConfigured() { return this._streamingConfigured; }

  /** Whether the Alpaca WS is currently connected. */
  get streamingHealthy() { return this._streamingHealthy; }

  /** Whether reconnect attempts have been exhausted (terminal). */
  get streamingDead() { return this._streamingDead; }

  async connect() {
    this.nc = await connect({
      servers: this.config.NATS_URL,
      maxReconnectAttempts: NATS_MAX_RECONNECT_ATTEMPTS,
      reconnectTimeWait: NATS_RECONNECT_WAIT_MS,
    });
    console.log('AlpacaStreamer: connected to NATS');

    this.natsMonitor = (async () => {
      if (!this.nc) return;
      try {
        for await (const status of this.nc.status()) {
          switch (status.type) {
            case 'reconnecting':
              console.warn(`AlpacaStreamer: NATS reconnecting (${status.data})`);
              break;
            case 'reconnect':
              console.log('AlpacaStreamer: NATS reconnected');
              break;
            case 'disconnect':
              console.warn('AlpacaStreamer: NATS disconnected');
              break;
            case 'error':
              console.error('AlpacaStreamer: NATS error', status.data);
              break;
          }
        }
      } catch (err) {
        console.error('AlpacaStreamer: NATS status monitor error', err);
      }
    })();
  }

  /**
   * Subscribe to real-time bar data.
   * Resolves once the Alpaca WS is connected, rejects on initial connection error.
   */
  subscribeToDataStream(symbols: string[]): Promise<void> {
    if (!this.nc) return Promise.reject(new Error('NATS not connected'));
    if (this.stream) return Promise.reject(new Error('Already subscribed to data stream'));
    this._streamingConfigured = true;
    this.streamSymbols = symbols;

    this.alpacaInstance = new AlpacaAPI({
      keyId: this.config.ALPACA_API_KEY,
      secretKey: this.config.ALPACA_API_SECRET,
      paper: this.config.TRADING_MODE === 'paper',
    });
    this.stream = this.alpacaInstance.data_stream_v2;

    return this.initStream();
  }

  /**
   * Register all handlers once on the single stream instance and connect.
   * Returns a promise that settles on the first onConnect or onError.
   */
  private initStream(): Promise<void> {
    const stream = this.stream!;

    return new Promise<void>((resolve, reject) => {
      let initialSettled = false;
      let sessionAborted = false;

      stream.onConnect(() => {
        this._streamingHealthy = true;
        this._streamingDead = false;
        this.wsRetryMs = WS_INITIAL_RETRY_MS;
        this.wsRetryCount = 0;
        console.log('Alpaca data stream connected');
        stream.subscribeForBars(this.streamSymbols);
        if (!initialSettled) { initialSettled = true; resolve(); }
      });

      stream.onBar((bar: AlpacaStreamBar) => {
        if (!this.nc || this.nc.isClosed()) {
          barsDroppedTotal.inc({ reason: 'nats_unavailable' });
          console.warn('AlpacaStreamer: NATS unavailable, dropping bar for', bar.Symbol);
          return;
        }

        const parsed = BarEventSchema.safeParse({
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
          timeframe: STREAM_TIMEFRAME,
        });

        if (!parsed.success) {
          barsDroppedTotal.inc({ reason: 'invalid_payload' });
          console.error('AlpacaStreamer: invalid bar payload, dropping', parsed.error.flatten());
          return;
        }

        this.nc.publish(
          `${SUBJECTS.MARKET_BAR_1M}.${parsed.data.symbol}`,
          this.sc.encode(JSON.stringify(parsed.data)),
        );
      });

      stream.onDisconnect(() => {
        if (sessionAborted) return;
        this._streamingHealthy = false;
        this.wsRetryCount++;

        if (this.wsRetryCount > WS_MAX_RECONNECT_ATTEMPTS) {
          this._streamingDead = true;
          console.error(
            `AlpacaStreamer: WS reconnect attempts exhausted (${WS_MAX_RECONNECT_ATTEMPTS}). Streaming is dead.`,
          );
          return;
        }

        const delay = this.wsRetryMs;
        this.wsRetryMs = Math.min(this.wsRetryMs * 2, WS_MAX_RETRY_MS);
        console.warn(
          `Alpaca data stream disconnected — reconnecting in ${delay}ms ` +
          `(attempt ${this.wsRetryCount}/${WS_MAX_RECONNECT_ATTEMPTS})`,
        );

        this.reconnectTimer = setTimeout(() => {
          this.reconnectTimer = null;
          if (this.closed) return;
          try { stream.connect(); } catch (err) {
            console.error('AlpacaStreamer: stream.connect() threw on retry', err);
          }
        }, delay);
      });

      stream.onError((err: Error) => {
        console.error('Alpaca stream error:', err.message);
        if (!initialSettled) {
          initialSettled = true;
          sessionAborted = true;
          // Clear stream so the caller can retry subscribeToDataStream
          this.stream = null;
          this.alpacaInstance = null;
          reject(err);
        }
      });

      stream.connect();
    });
  }

  async publishOrderEvent(subject: string, payload: object) {
    if (!this.nc || this.nc.isClosed()) return;
    this.nc.publish(subject, this.sc.encode(JSON.stringify(payload)));
  }

  async close() {
    this.closed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    try { this.stream?.disconnect(); } catch { /* may already be disconnected */ }
    await this.nc?.drain();
    // Race the NATS status iterator termination against a 5s safety timeout
    await Promise.race([
      this.natsMonitor ?? Promise.resolve(),
      new Promise<void>((resolve) => setTimeout(resolve, 5_000)),
    ]);
  }
}
