import type { FastifyBaseLogger } from 'fastify';
import { Config } from '@alpaca-rl/config';
import { RiskDb } from './riskDb.js';

const FETCH_TIMEOUT_MS = 30_000;

// Keeps risk_state.portfolio_value fresh by polling the internal portfolio
// service (account_snapshot table) on a cadence well under
// MAX_PORTFOLIO_STALENESS_S. Reads from portfolio/account, which mirrors
// Alpaca's field names but is a locally-cached snapshot — its own staleness
// must be checked before trusting the data.
export class PortfolioSyncCron {
  private timer: ReturnType<typeof setInterval> | null = null;
  private inFlight = false;

  constructor(
    private config: Config,
    private db: RiskDb,
    private log: Pick<FastifyBaseLogger, 'info' | 'warn' | 'error'>,
  ) {}

  start() {
    if (this.timer) return;
    const intervalMs = this.config.RISK_PORTFOLIO_SYNC_INTERVAL_MS;
    this.run().catch((err) =>
      this.log.error({ err: String(err) }, '[risk-portfolio-sync] initial run failed'),
    );
    this.timer = setInterval(() => {
      this.run().catch((err) =>
        this.log.error({ err: String(err) }, '[risk-portfolio-sync] sync failed'),
      );
    }, intervalMs);
    this.log.info({ intervalMs }, '[risk-portfolio-sync] started');
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  // Public so tests can exercise behaviour without going through the timer.
  async run(): Promise<void> {
    if (this.inFlight) {
      this.log.warn('[risk-portfolio-sync] previous sync still in flight — skipping');
      return;
    }
    this.inFlight = true;
    try {
      await this.doRun();
    } finally {
      this.inFlight = false;
    }
  }

  private async doRun(): Promise<void> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    let res: Response;
    try {
      res = await fetch(`${this.config.PORTFOLIO_URL}/portfolio/account`, {
        signal: controller.signal,
      });
    } catch (err: unknown) {
      const isTimeout = err instanceof Error && err.name === 'AbortError';
      this.log.warn(
        { err: String(err) },
        isTimeout
          ? '[risk-portfolio-sync] fetch timed out after 30 s'
          : '[risk-portfolio-sync] fetch error',
      );
      return;
    } finally {
      clearTimeout(timeout);
    }

    if (!res.ok) {
      this.log.warn(
        { status: res.status },
        '[risk-portfolio-sync] portfolio/account returned non-ok',
      );
      return;
    }

    // portfolioDb.ts returns rows[0] ?? null — null on a fresh deployment
    // with no account_snapshot rows yet.
    const account = (await res.json()) as Record<string, unknown> | null;
    if (account == null) {
      this.log.warn('[risk-portfolio-sync] portfolio/account returned null — no snapshot yet');
      return;
    }

    const raw = account['portfolio_value'] ?? account['equity'];
    const portfolioValue = Number(raw);
    if (!Number.isFinite(portfolioValue) || portfolioValue <= 0) {
      this.log.warn(
        { raw },
        '[risk-portfolio-sync] invalid portfolio_value received — skipping update',
      );
      return;
    }

    // Use the upstream snapshot's own timestamp (account_snapshot.created_at)
    // as the data-age marker instead of NOW(). Writing NOW() would lie about
    // freshness when the portfolio service's SyncCron is dead and
    // getLatestAccount is returning stale rows — the /risk/check staleness
    // gate would then pass on data that is actually hours old.
    const rawCreatedAt = account['created_at'];
    const asOf = typeof rawCreatedAt === 'string' ? new Date(rawCreatedAt) : new Date();

    const ageMs = Date.now() - asOf.getTime();
    if (ageMs > this.config.MAX_PORTFOLIO_STALENESS_S * 1000) {
      this.log.warn(
        { ageMs, thresholdMs: this.config.MAX_PORTFOLIO_STALENESS_S * 1000 },
        '[risk-portfolio-sync] upstream snapshot is older than staleness threshold — skipping',
      );
      return;
    }

    const { prior } = await this.db.updatePortfolioValue(portfolioValue, asOf);
    this.log.info(
      { prior, next: portfolioValue, asOf },
      '[risk-portfolio-sync] portfolio_value synced',
    );
  }
}
