const BASE = '/api'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(body.detail || body.error || `HTTP ${resp.status}`)
  }
  if (resp.status === 204) return null as T
  return resp.json()
}

// ── Dashboard ──────────────────────────────────────────────
export const fetchOverview   = () => request<DashboardOverview>('/dashboard/overview')
export const fetchServices   = () => request<ServiceHealth>('/dashboard/services')
export const fetchActivity   = (limit = 20) => request<ActivityFeed>(`/dashboard/activity?limit=${limit}`)

// ── Training / Kaggle ──────────────────────────────────────
export const startTraining   = (payload: TrainPayload) => request<TrainResponse>('/kaggle/train', { method: 'POST', body: JSON.stringify(payload) })
export const fetchJobs       = (status?: string) => request<KaggleJob[]>(`/kaggle/jobs${status ? `?status=${status}` : ''}`)
export const fetchJob        = (id: string) => request<KaggleJob>(`/kaggle/jobs/${id}`)
export const cancelJob       = (id: string) => request<KaggleJob>(`/kaggle/jobs/${id}/cancel`, { method: 'POST' })
export const approveJob      = (id: string) => request<ApprovalResponse>(`/kaggle/jobs/${id}/approve-promotion`, { method: 'POST', body: JSON.stringify({ approved_by: 'admin' }) })
export const rejectJob       = (id: string, reason?: string) => request<ApprovalResponse>(`/kaggle/jobs/${id}/reject-promotion`, { method: 'POST', body: JSON.stringify({ reason }) })
export const fetchQuota      = () => request<KaggleQuota>('/kaggle/quota')

// ── Backtest ───────────────────────────────────────────────
export const runBacktest     = (payload: BacktestPayload) => request<BacktestResponse>('/backtest/run', { method: 'POST', body: JSON.stringify(payload) })
export const fetchBacktests  = (limit = 50) => request<BacktestRow[]>(`/backtest?limit=${limit}`)
export const fetchBacktest   = (id: string) => request<BacktestResult>(`/backtest/${id}`)
export const fetchCharts     = (id: string) => request<BacktestCharts>(`/backtest/${id}/charts`)

// ── Policies ───────────────────────────────────────────────
export const fetchPolicies   = (promotedOnly = false) => request<Policy[]>(`/rl/policies${promotedOnly ? '?promoted_only=true' : ''}`)
export const fetchPolicy     = (id: string) => request<Policy>(`/rl/policies/${id}`)
export const approvePolicy   = (id: string) => request<unknown>(`/rl/policies/${id}/approve?approved_by=admin`, { method: 'POST' })
export const rejectPolicy    = (id: string, reason?: string) => request<unknown>(`/rl/policies/${id}/reject?reason=${reason || ''}`, { method: 'POST' })
export const promotePolicy   = (id: string) => request<unknown>(`/rl/policies/${id}/promote?promoted_by=admin`, { method: 'POST' })
export const deletePolicy    = (id: string) => request<void>(`/rl/policies/${id}`, { method: 'DELETE' })

// ── Datasets ───────────────────────────────────────────────
export const fetchDatasets   = () => request<Dataset[]>('/datasets')
export const fetchDataset    = (id: string) => request<Dataset>(`/datasets/${id}`)
export const deleteDataset   = (id: string) => request<void>(`/datasets/${id}`, { method: 'DELETE' })
export const buildDataset    = (payload: BuildDatasetPayload) => request<BuildDatasetResponse>('/datasets/build', { method: 'POST', body: JSON.stringify(payload) })

// ── Market / Ingest ────────────────────────────────────────
export const fetchSymbols    = () => request<string[]>('/market/symbols')
export const checkBarData    = (symbols: string[], startDate: string, endDate: string, timeframe: '1m' | '1d') =>
  request<BarAvailability[]>(`/market/availability?symbols=${symbols.join(',')}&start=${startDate}&end=${endDate}&timeframe=${timeframe}`)
export const backfillData    = (payload: BackfillPayload) => request<BackfillResponse>('/market/backfill', { method: 'POST', body: JSON.stringify(payload) })

// ── Features ───────────────────────────────────────────────
export const checkFeatureAvailability = (symbols: string[], startDate: string, endDate: string) =>
  request<Record<string, FeatureAvailability>>(`/features/availability?symbols=${symbols.join(',')}&start_date=${startDate}&end_date=${endDate}`)
export const computeFeatures = (payload: ComputeFeaturesPayload) => request<Record<string, unknown>>('/features/compute', { method: 'POST', body: JSON.stringify(payload) })

// ── Config ─────────────────────────────────────────────────
export const fetchConfig     = () => request<{ grafanaUrl: string }>('/config')


// ── Types ──────────────────────────────────────────────────
export interface DashboardOverview {
  systemStatus: string
  checkedAt: string
  services: ServiceStatus[]
  stats: SystemStats
  pendingApprovals: number
  activeJobs: number
}

export interface ServiceHealth {
  services: ServiceStatus[]
  checkedAt: string
}

export interface ServiceStatus {
  service: string
  status: string
  latencyMs: number | null
  error?: string
}

export interface SystemStats {
  totalTrainingJobs: number
  completedJobs: number
  failedJobs: number
  pendingApprovals: number
  promotedPolicies: number
  totalBacktests: number
  completedBacktests: number
  totalDatasets: number
}

export interface ActivityFeed {
  events: ActivityEvent[]
  generatedAt: string
}

export interface ActivityEvent {
  type: string
  id: string
  name: string
  status: string
  subStatus: string | null
  timestamp: string
}

export interface TrainPayload {
  name: string
  symbols: string[]
  totalTimesteps?: number
  kernelSlug?: string
  learningRate?: number
  batchSize?: number
  gamma?: number
}

export interface TrainResponse {
  jobId: string
  status: string
  name: string
  message: string
}

export interface KaggleJob {
  id: string
  name: string
  status: string
  approval_status: string
  config_hash: string
  config?: Record<string, unknown>
  metadata?: Record<string, unknown>
  error?: string
  created_at: string
  updated_at: string
  completed_at?: string
}

export interface KaggleQuota {
  username?: string
  gpuQuota?: number
  gpuUsed?: number
  gpuRemaining?: number
  error?: string
}

export interface ApprovalResponse {
  jobId: string
  approvalStatus: string
  approvedBy?: string
  policyId?: string
  reason?: string
}

export interface BacktestPayload {
  name: string
  symbols: string[]
  startDate: string
  endDate: string
  initialCapital?: number
  policyId?: string
}

export interface BacktestResponse {
  reportId: string
  status: string
}

export interface BacktestRow {
  id: string
  name: string
  status: string
  config_hash: string
  created_at: string
}

export interface BacktestResult {
  id: string
  name: string
  status: string
  metrics?: BacktestMetrics
  error?: string
}

export interface BacktestMetrics {
  avgSharpe: number
  avgTotalReturn: number
  avgMaxDrawdown: number
  avgWinRate: number
  perSymbol?: PerSymbolMetrics[]
  chartPaths?: Record<string, string>
}

export interface PerSymbolMetrics {
  symbol: string
  sharpeRatio: number
  totalReturn: number
  maxDrawdown: number
  winRate: number
}

export interface BacktestCharts {
  reportId: string
  chartPaths: Record<string, string>
  symbols: string[]
}

export interface Policy {
  id: string
  name: string
  version: string
  promoted: boolean
  approval_status: string
  approved_by?: string
  approved_at?: string
  created_at: string
  s3_path: string
  metrics?: Record<string, unknown>
}

export interface Dataset {
  id: string
  name: string
  symbols: string[]
  start_date: string
  end_date: string
  n_splits: number
  s3_path: string
  created_at: string
}

export interface BuildDatasetPayload {
  name: string
  symbols: string[]
  start_date: string
  end_date: string
  n_splits: number
  train_frac: number
  feature_version?: string
}

export interface BuildDatasetResponse {
  datasetId: string
  name: string
  configHash: string
  nRows: number
  nSplits: number
  s3Path: string
}

export interface BackfillPayload {
  symbols: string[]
  startDate: string
  endDate: string
  timeframe: '1m' | '1d'
}

export interface BackfillResponse {
  jobId: string
  status: string
  symbols: string[]
  message: string
}

export interface BarAvailability {
  symbol: string
  available: number
  expected: number
  pct: number
}

export interface FeatureAvailability {
  feature_rows: number
  bar_rows: number
}

export interface ComputeFeaturesPayload {
  symbols: string[]
  start_date: string
  end_date: string
}
