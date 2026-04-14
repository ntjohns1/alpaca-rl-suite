import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Hoisted mocks (must be defined before vi.mock factories run) ─────
const { mockAck, mockNak, mockConsume, mockJsm, mockNc, mockUpsertBar } =
  vi.hoisted(() => {
    const mockAck  = vi.fn();
    const mockNak  = vi.fn();
    const mockConsume = vi.fn();
    const mockGetConsumer = vi.fn().mockResolvedValue({ consume: mockConsume });
    const mockJsm = {
      streams:   { add: vi.fn().mockResolvedValue(undefined) },
      consumers: { add: vi.fn().mockResolvedValue(undefined) },
    };
    const mockJs = { consumers: { get: mockGetConsumer } };
    const mockNc = {
      jetstreamManager: vi.fn().mockResolvedValue(mockJsm),
      jetstream:        vi.fn().mockReturnValue(mockJs),
      drain:            vi.fn().mockResolvedValue(undefined),
    };
    const mockUpsertBar = vi.fn().mockResolvedValue(undefined);
    return { mockAck, mockNak, mockConsume, mockJsm, mockNc, mockUpsertBar };
  });

vi.mock('nats', () => ({
  connect:         vi.fn().mockResolvedValue(mockNc),
  StringCodec:     vi.fn(() => ({ decode: (d: Uint8Array) => new TextDecoder().decode(d) })),
  AckPolicy:       { Explicit: 'explicit' },
  DeliverPolicy:   { New: 'new' },
  RetentionPolicy: { Limits: 'limits' },
  StorageType:     { File: 'file' },
}));

vi.mock('../dbClient', () => ({
  DbClient: vi.fn(() => ({ upsertBar: mockUpsertBar })),
}));

function makeMockMsg(payload: unknown) {
  return {
    data: new TextEncoder().encode(JSON.stringify(payload)),
    ack:  mockAck,
    nak:  mockNak,
  };
}

// ── Import after mocks ────────────────────────────────────────────────
import { NatsBarConsumer } from '../natsConsumer';

const mockConfig = {
  NATS_URL: 'nats://localhost:4222',
} as any;

const validBar1d = {
  traceId:    'trace-1',
  symbol:     'AAPL',
  time:       '2024-01-02T00:00:00.000Z',
  open:       180.0,
  high:       182.5,
  low:        179.0,
  close:      181.0,
  volume:     5_000_000,
  vwap:       180.5,
  tradeCount: 42000,
  timeframe:  '1d',
};

describe('NatsBarConsumer', () => {
  let consumer: NatsBarConsumer;

  beforeEach(() => {
    vi.clearAllMocks();
    consumer = new NatsBarConsumer(mockConfig, { upsertBar: mockUpsertBar } as any);
  });

  it('connects and ensures MARKET_BARS stream exists', async () => {
    await consumer.connect();
    expect(mockNc.jetstreamManager).toHaveBeenCalledOnce();
    expect(mockJsm.streams.add).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'MARKET_BARS' }),
    );
  });

  it('acks a valid 1d bar and upserts it to bar_1d', async () => {
    const msg = makeMockMsg(validBar1d);
    // Simulate consume() returning an async iterable with one message
    mockConsume.mockResolvedValue({
      [Symbol.asyncIterator]: async function* () { yield msg; },
    });

    await consumer.connect();
    await consumer.startConsuming();
    // Give the async loop a tick to process
    await new Promise(r => setTimeout(r, 20));

    expect(mockUpsertBar).toHaveBeenCalledWith('bar_1d', expect.objectContaining({
      symbol: 'AAPL',
      close:  181.0,
    }));
    expect(mockAck).toHaveBeenCalledOnce();
  });

  it('acks a valid 1m bar and upserts it to bar_1m', async () => {
    const bar1m = { ...validBar1d, timeframe: '1m' };
    const msg = makeMockMsg(bar1m);
    mockConsume.mockResolvedValue({
      [Symbol.asyncIterator]: async function* () { yield msg; },
    });

    await consumer.connect();
    await consumer.startConsuming();
    await new Promise(r => setTimeout(r, 20));

    expect(mockUpsertBar).toHaveBeenCalledWith('bar_1m', expect.objectContaining({ symbol: 'AAPL' }));
  });

  it('acks (skips) a message with invalid payload without crashing', async () => {
    const msg = makeMockMsg({ bad: 'data' });
    mockConsume.mockResolvedValue({
      [Symbol.asyncIterator]: async function* () { yield msg; },
    });

    await consumer.connect();
    await consumer.startConsuming();
    await new Promise(r => setTimeout(r, 20));

    expect(mockUpsertBar).not.toHaveBeenCalled();
    expect(mockAck).toHaveBeenCalledOnce();
  });

  it('naks a message when upsertBar throws', async () => {
    mockUpsertBar.mockRejectedValueOnce(new Error('DB down'));
    const msg = makeMockMsg(validBar1d);
    mockConsume.mockResolvedValue({
      [Symbol.asyncIterator]: async function* () { yield msg; },
    });

    await consumer.connect();
    await consumer.startConsuming();
    await new Promise(r => setTimeout(r, 20));

    expect(mockNak).toHaveBeenCalledOnce();
  });

  it('drains NATS connection on stop()', async () => {
    await consumer.connect();
    await consumer.stop();
    expect(mockNc.drain).toHaveBeenCalledOnce();
  });
});
