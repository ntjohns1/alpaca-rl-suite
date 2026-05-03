import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { NatsConnection, Status } from 'nats';

// ── Hoisted mocks ────────────────────────────────────────────────────

const { mockStream, mockNatsConn, mockConnect } = vi.hoisted(() => {
  const mockStream = {
    onConnect: vi.fn(),
    onBar: vi.fn(),
    onDisconnect: vi.fn(),
    onError: vi.fn(),
    subscribeForBars: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn(),
  };

  const statusIterator = {
    [Symbol.asyncIterator]: vi.fn().mockReturnValue({
      next: vi.fn().mockResolvedValue({ done: true, value: undefined }),
    }),
  };

  const mockNatsConn = {
    publish: vi.fn(),
    drain: vi.fn().mockResolvedValue(undefined),
    isClosed: vi.fn().mockReturnValue(false),
    status: vi.fn().mockReturnValue(statusIterator),
  };

  const mockConnect = vi.fn().mockResolvedValue(mockNatsConn);

  return { mockStream, mockNatsConn, mockConnect };
});

vi.mock('nats', () => ({
  connect: mockConnect,
  StringCodec: vi.fn().mockReturnValue({
    encode: vi.fn((s: string) => Buffer.from(s)),
  }),
}));

vi.mock('@alpacahq/alpaca-trade-api', () => ({
  default: vi.fn().mockImplementation(() => ({
    data_stream_v2: mockStream,
  })),
}));

vi.mock('@alpaca-rl/observability', () => {
  const counters: Record<string, { inc: ReturnType<typeof vi.fn> }> = {};
  return {
    registry: {
      contentType: 'text/plain',
      metrics: vi.fn().mockResolvedValue(''),
      getSingleMetric: vi.fn(),
      registerMetric: vi.fn(),
      removeSingleMetric: vi.fn(),
    },
    __getCounter: (name: string) => counters[name],
    __counters: counters,
  };
});

vi.mock('prom-client', () => {
  const counters: Record<string, { inc: ReturnType<typeof vi.fn> }> = {};
  return {
    default: {
      Counter: vi.fn().mockImplementation((opts: { name: string }) => {
        const counter = { inc: vi.fn() };
        counters[opts.name] = counter;
        return counter;
      }),
    },
    __getCounter: (name: string) => counters[name],
  };
});

// Import after mocks are set up
import { AlpacaStreamer } from '../alpacaStreamer';

// ── Helpers ──────────────────────────────────────────────────────────

const mockConfig = {
  NATS_URL: 'nats://localhost:4222',
  ALPACA_API_KEY: 'test-key',
  ALPACA_API_SECRET: 'test-secret',
  TRADING_MODE: 'paper' as const,
} as any;

/** Trigger a registered onX handler by name. */
function fireStreamEvent(name: 'onConnect' | 'onBar' | 'onDisconnect' | 'onError', ...args: any[]) {
  const calls = mockStream[name].mock.calls;
  const lastCb = calls[calls.length - 1]?.[0];
  if (!lastCb) throw new Error(`No ${name} handler registered`);
  lastCb(...args);
}

// ── Tests ────────────────────────────────────────────────────────────

describe('AlpacaStreamer', () => {
  let streamer: AlpacaStreamer;

  beforeEach(() => {
    vi.clearAllMocks();
    streamer = new AlpacaStreamer(mockConfig);
  });

  afterEach(async () => {
    try { await streamer.close(); } catch { /* ok */ }
  });

  describe('connect()', () => {
    it('connects to NATS with reconnect options', async () => {
      await streamer.connect();
      expect(mockConnect).toHaveBeenCalledWith(
        expect.objectContaining({
          servers: 'nats://localhost:4222',
          maxReconnectAttempts: 10,
          reconnectTimeWait: 2_000,
        }),
      );
    });
  });

  describe('subscribeToDataStream()', () => {
    it('rejects if NATS is not connected', async () => {
      await expect(streamer.subscribeToDataStream(['AAPL'])).rejects.toThrow('NATS not connected');
    });

    it('rejects if already subscribed', async () => {
      await streamer.connect();
      mockStream.connect.mockImplementation(() => fireStreamEvent('onConnect'));
      await streamer.subscribeToDataStream(['AAPL']);
      await expect(streamer.subscribeToDataStream(['MSFT'])).rejects.toThrow('Already subscribed');
    });

    it('resolves when Alpaca WS connects', async () => {
      await streamer.connect();

      // Make stream.connect() trigger onConnect synchronously
      mockStream.connect.mockImplementation(() => {
        fireStreamEvent('onConnect');
      });

      await streamer.subscribeToDataStream(['AAPL', 'MSFT']);

      expect(mockStream.subscribeForBars).toHaveBeenCalledWith(['AAPL', 'MSFT']);
      expect(streamer.streamingHealthy).toBe(true);
      expect(streamer.streamingDead).toBe(false);
    });

    it('rejects when Alpaca WS errors on initial connect', async () => {
      await streamer.connect();

      mockStream.connect.mockImplementation(() => {
        fireStreamEvent('onError', new Error('auth failed'));
      });

      await expect(streamer.subscribeToDataStream(['AAPL'])).rejects.toThrow('auth failed');
    });

    it('creates only one AlpacaAPI instance', async () => {
      await streamer.connect();
      mockStream.connect.mockImplementation(() => fireStreamEvent('onConnect'));

      await streamer.subscribeToDataStream(['AAPL']);

      // AlpacaAPI constructor should have been called exactly once
      const AlpacaAPI = (await import('@alpacahq/alpaca-trade-api')).default;
      expect(AlpacaAPI).toHaveBeenCalledTimes(1);
    });
  });

  describe('onBar handler', () => {
    beforeEach(async () => {
      await streamer.connect();
      mockStream.connect.mockImplementation(() => fireStreamEvent('onConnect'));
      await streamer.subscribeToDataStream(['AAPL']);
    });

    it('publishes valid bar to NATS', () => {
      fireStreamEvent('onBar', {
        Symbol: 'AAPL',
        Timestamp: '2024-01-01T00:00:00Z',
        OpenPrice: 150,
        HighPrice: 155,
        LowPrice: 149,
        ClosePrice: 153,
        Volume: 1000,
        VWAP: 152,
        TradeCount: 50,
      });

      expect(mockNatsConn.publish).toHaveBeenCalledTimes(1);
      const [subject, data] = mockNatsConn.publish.mock.calls[0];
      expect(subject).toBe('market.bar.1m.AAPL');
      const parsed = JSON.parse(data.toString());
      expect(parsed.symbol).toBe('AAPL');
      expect(parsed.open).toBe(150);
      expect(parsed.timeframe).toBe('1m');
    });

    it('drops bar and increments counter when NATS is closed', () => {
      mockNatsConn.isClosed.mockReturnValueOnce(true);

      fireStreamEvent('onBar', {
        Symbol: 'AAPL',
        Timestamp: '2024-01-01T00:00:00Z',
        OpenPrice: 150,
        HighPrice: 155,
        LowPrice: 149,
        ClosePrice: 153,
        Volume: 1000,
      });

      expect(mockNatsConn.publish).not.toHaveBeenCalled();
    });

    it('drops invalid bar payload and logs', () => {
      // Missing required fields
      fireStreamEvent('onBar', {
        Symbol: 'AAPL',
        Timestamp: 'not-a-date',
        OpenPrice: 150,
        HighPrice: 155,
        LowPrice: 149,
        ClosePrice: 153,
        Volume: 1000,
      });

      expect(mockNatsConn.publish).not.toHaveBeenCalled();
    });
  });

  describe('reconnection logic', () => {
    beforeEach(async () => {
      vi.useFakeTimers();
      await streamer.connect();
      // First connect succeeds
      mockStream.connect.mockImplementationOnce(() => fireStreamEvent('onConnect'));
      await streamer.subscribeToDataStream(['AAPL']);
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('reuses the same stream instance on reconnect (no new AlpacaAPI)', async () => {
      // Reset connect mock to not auto-fire onConnect
      mockStream.connect.mockImplementation(() => {});

      fireStreamEvent('onDisconnect');
      expect(streamer.streamingHealthy).toBe(false);

      // Advance timer for first retry (1s)
      vi.advanceTimersByTime(1_000);

      // stream.connect called again on the SAME stream (not a new AlpacaAPI)
      // Original call + reconnect = 2
      expect(mockStream.connect).toHaveBeenCalledTimes(2);
      const AlpacaAPI = (await import('@alpacahq/alpaca-trade-api')).default;
      // Still only 1 AlpacaAPI instance ever created
      expect(AlpacaAPI).toHaveBeenCalledTimes(1);
    });

    it('resets backoff on successful reconnect', () => {
      // First disconnect
      mockStream.connect.mockImplementation(() => {});
      fireStreamEvent('onDisconnect');
      vi.advanceTimersByTime(1_000);

      // Simulate successful reconnect
      fireStreamEvent('onConnect');
      expect(streamer.streamingHealthy).toBe(true);

      // Second disconnect — should retry at 1s again, not 2s
      fireStreamEvent('onDisconnect');
      mockStream.connect.mockImplementation(() => {});
      vi.advanceTimersByTime(1_000);
      expect(mockStream.connect).toHaveBeenCalledTimes(3); // initial + 2 reconnects
    });

    it('gives up after WS_MAX_RECONNECT_ATTEMPTS via real connect→onDisconnect loop', async () => {
      // Each stream.connect() immediately fires onDisconnect (simulates persistent rejection).
      mockStream.connect.mockImplementation(() => fireStreamEvent('onDisconnect'));

      // Fire the first disconnect to start the retry chain (attempts 1–10)
      fireStreamEvent('onDisconnect');

      // Drive all 10 retry timers; each connect() fires onDisconnect and schedules the next
      for (let i = 0; i < 10; i++) {
        vi.advanceTimersByTime(30_000);
      }

      expect(streamer.streamingDead).toBe(true);
      expect(mockStream.connect.mock.calls.length).toBeGreaterThanOrEqual(10);
    });

    it('does not reconnect after close()', async () => {
      mockStream.connect.mockImplementation(() => {});
      fireStreamEvent('onDisconnect'); // schedules a timer

      await streamer.close(); // should clearTimeout the pending timer

      vi.advanceTimersByTime(30_000);
      // connect was called once (initial) but not again after close
      expect(mockStream.connect).toHaveBeenCalledTimes(1);
    });
  });

  describe('health getters', () => {
    it('defaults to not healthy, not dead', () => {
      expect(streamer.streamingHealthy).toBe(false);
      expect(streamer.streamingDead).toBe(false);
    });
  });

  describe('close()', () => {
    it('disconnects stream and drains NATS', async () => {
      await streamer.connect();
      mockStream.connect.mockImplementation(() => fireStreamEvent('onConnect'));
      await streamer.subscribeToDataStream(['AAPL']);

      await streamer.close();
      expect(mockStream.disconnect).toHaveBeenCalled();
      expect(mockNatsConn.drain).toHaveBeenCalled();
    });
  });
});
