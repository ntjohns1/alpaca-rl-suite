import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  runBacktest, fetchBacktests, fetchBacktest, fetchPolicies,
  type BacktestRow, type BacktestMetrics, type PerSymbolMetrics, type Policy,
} from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StatusBadge } from '@/components/StatusBadge'
import {
  BarChart3, Plus, X, Loader2, CheckCircle2, XCircle,
  TrendingUp, TrendingDown, Target, MinusCircle, ChevronDown, ChevronUp,
} from 'lucide-react'

export function Backtests() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: backtests = [], isLoading } = useQuery({
    queryKey: ['backtests'],
    queryFn: () => fetchBacktests(),
    refetchInterval: 15_000,
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Backtests</h1>
          <p className="text-muted-foreground">Run and review backtests against trained models.</p>
        </div>
        <div className="flex items-center gap-3">
          {backtests.length > 0 && (
            <span className="text-sm text-muted-foreground">
              {backtests.length} backtests
            </span>
          )}
          {!showForm && (
            <Button size="sm" onClick={() => setShowForm(true)} className="gap-1.5">
              <Plus className="h-4 w-4" /> Run Backtest
            </Button>
          )}
        </div>
      </div>

      {showForm && (
        <BacktestForm
          onClose={() => setShowForm(false)}
          onSuccess={() => {
            setShowForm(false)
            queryClient.invalidateQueries({ queryKey: ['backtests'] })
          }}
        />
      )}

      <Card>
        <CardHeader><CardTitle className="text-lg">Backtest Results</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : backtests.length === 0 ? (
            <div className="py-8 text-center space-y-3">
              <BarChart3 className="h-10 w-10 mx-auto text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No backtests yet.</p>
              {!showForm && (
                <Button size="sm" variant="outline" onClick={() => setShowForm(true)} className="gap-1.5">
                  <Plus className="h-4 w-4" /> Run your first backtest
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium w-8"></th>
                    <th className="pb-2 font-medium">Name</th>
                    <th className="pb-2 font-medium">Status</th>
                    <th className="pb-2 font-medium">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {backtests.map((bt: BacktestRow) => (
                    <BacktestTableRow
                      key={bt.id}
                      backtest={bt}
                      isExpanded={expandedId === bt.id}
                      onToggle={() => setExpandedId(expandedId === bt.id ? null : bt.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Run Backtest Form ─────────────────────────────────────

function BacktestForm({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [name, setName] = useState('')
  const [symbols, setSymbols] = useState('SPY')
  const [startDate, setStartDate] = useState('2024-01-01')
  const [endDate, setEndDate] = useState('2024-12-31')
  const [initialCapital, setInitialCapital] = useState(100000)
  const [policyId, setPolicyId] = useState('')

  const { data: policies = [] } = useQuery({
    queryKey: ['policies'],
    queryFn: () => fetchPolicies(),
  })

  const mutation = useMutation({
    mutationFn: runBacktest,
    onSuccess,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const symArray = symbols.split(',').map(s => s.trim().toUpperCase()).filter(Boolean)
    mutation.mutate({
      name: name || `backtest-${symArray.join('-')}-${Date.now()}`,
      symbols: symArray,
      startDate,
      endDate,
      initialCapital,
      ...(policyId ? { policyId } : {}),
    })
  }

  const isValid = symbols.trim().length > 0 && startDate && endDate && startDate < endDate

  return (
    <Card className="border-primary/30">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-primary" />
            Run Backtest
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Name <span className="text-muted-foreground font-normal">(optional)</span></label>
              <Input placeholder="e.g. SPY-2024-test" value={name}
                onChange={e => setName(e.target.value)} disabled={mutation.isPending} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Symbols <span className="text-muted-foreground font-normal">(comma-separated)</span></label>
              <Input placeholder="SPY, AAPL" value={symbols}
                onChange={e => setSymbols(e.target.value)} disabled={mutation.isPending} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Start Date</label>
              <Input type="date" value={startDate}
                onChange={e => setStartDate(e.target.value)} disabled={mutation.isPending} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">End Date</label>
              <Input type="date" value={endDate}
                onChange={e => setEndDate(e.target.value)} disabled={mutation.isPending} />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Initial Capital</label>
              <Input type="number" value={initialCapital} min={1000} step={10000}
                onChange={e => setInitialCapital(Number(e.target.value))} disabled={mutation.isPending} />
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Policy / Model <span className="text-muted-foreground font-normal">(optional)</span></label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={policyId} onChange={e => setPolicyId(e.target.value)}
              disabled={mutation.isPending}>
              <option value="">— Select a policy —</option>
              {policies.map((p: Policy) => (
                <option key={p.id} value={p.id}>
                  {p.name} (v{p.version}){p.promoted ? ' [promoted]' : ''}
                </option>
              ))}
            </select>
          </div>

          {mutation.isError && (
            <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <XCircle className="h-4 w-4" />
              {(mutation.error as Error)?.message || 'Backtest failed to start'}
            </div>
          )}

          {mutation.isSuccess && (
            <div className="flex items-center gap-2 rounded-md bg-green-500/10 px-3 py-2 text-sm text-green-700">
              <CheckCircle2 className="h-4 w-4" />
              Backtest started successfully!
            </div>
          )}
        </form>
      </CardContent>
      <CardFooter className="border-t pt-4 gap-2">
        <Button onClick={handleSubmit} disabled={!isValid || mutation.isPending} className="gap-1.5">
          {mutation.isPending
            ? <><Loader2 className="h-4 w-4 animate-spin" /> Running...</>
            : <><BarChart3 className="h-4 w-4" /> Run Backtest</>
          }
        </Button>
        <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>Cancel</Button>
      </CardFooter>
    </Card>
  )
}

// ── Backtest Table Row (expandable) ───────────────────────

function BacktestTableRow({ backtest, isExpanded, onToggle }: {
  backtest: BacktestRow
  isExpanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr className="border-b last:border-0 cursor-pointer hover:bg-muted/50 transition-colors"
        onClick={onToggle}>
        <td className="py-3">
          {isExpanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </td>
        <td className="py-3 font-medium">{backtest.name}</td>
        <td className="py-3"><StatusBadge status={backtest.status} /></td>
        <td className="py-3 text-muted-foreground">{new Date(backtest.created_at).toLocaleDateString()}</td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={4} className="pb-4 pt-0 px-2">
            <BacktestDetail id={backtest.id} />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Backtest Detail (metrics + per-symbol) ────────────────

function BacktestDetail({ id }: { id: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['backtest', id],
    queryFn: () => fetchBacktest(id),
  })

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading details...
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-destructive">
        <XCircle className="h-4 w-4" /> Failed to load backtest details.
      </div>
    )
  }

  if (data.error) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-destructive">
        <XCircle className="h-4 w-4" /> {data.error}
      </div>
    )
  }

  if (!data.metrics) {
    return (
      <p className="py-4 text-sm text-muted-foreground">No metrics available yet.</p>
    )
  }

  return (
    <div className="space-y-4 pt-2">
      <MetricsCards metrics={data.metrics} />
      {data.metrics.perSymbol && data.metrics.perSymbol.length > 0 && (
        <PerSymbolTable symbols={data.metrics.perSymbol} />
      )}
    </div>
  )
}

// ── Metrics Cards ─────────────────────────────────────────

function MetricsCards({ metrics }: { metrics: BacktestMetrics }) {
  const evalPass = (v: number | null | undefined, threshold: (n: number) => boolean): boolean | null =>
    v == null ? null : threshold(v)

  return (
    <div className="grid gap-3 sm:grid-cols-4">
      <MetricCard label="Sharpe Ratio" value={metrics.avgSharpe?.toFixed(3) ?? '-'} icon={TrendingUp}
        pass={evalPass(metrics.avgSharpe, n => n > 1.0)} />
      <MetricCard label="Max Drawdown"
        value={metrics.avgMaxDrawdown != null ? `${(metrics.avgMaxDrawdown * 100).toFixed(1)}%` : '-'}
        icon={TrendingDown} pass={evalPass(metrics.avgMaxDrawdown, n => n < 0.15)} />
      <MetricCard label="Win Rate"
        value={metrics.avgWinRate != null ? `${(metrics.avgWinRate * 100).toFixed(1)}%` : '-'}
        icon={Target} pass={evalPass(metrics.avgWinRate, n => n > 0.5)} />
      <MetricCard label="Total Return"
        value={metrics.avgTotalReturn != null ? `${(metrics.avgTotalReturn * 100).toFixed(2)}%` : '-'}
        icon={BarChart3} pass={evalPass(metrics.avgTotalReturn, n => n > 0)} />
    </div>
  )
}

function MetricCard({ label, value, icon: Icon, pass }: {
  label: string; value: string; icon: React.ComponentType<{ className?: string }>; pass: boolean | null
}) {
  const tone =
    pass === null  ? 'border-slate-200 bg-slate-50'
    : pass         ? 'border-green-200 bg-green-50'
    :                'border-red-200 bg-red-50'
  const indicator =
    pass === null ? <MinusCircle className="h-4 w-4 text-slate-400" />
    : pass        ? <CheckCircle2 className="h-4 w-4 text-green-600" />
    :               <XCircle className="h-4 w-4 text-red-500" />
  return (
    <div className={`rounded-lg border p-3 ${tone}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-xl font-bold">{value}</span>
        {indicator}
      </div>
    </div>
  )
}

// ── Per-Symbol Table ──────────────────────────────────────

function PerSymbolTable({ symbols }: { symbols: PerSymbolMetrics[] }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Per-Symbol Breakdown</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="pb-2 font-medium">Symbol</th>
              <th className="pb-2 font-medium">Sharpe</th>
              <th className="pb-2 font-medium">Total Return</th>
              <th className="pb-2 font-medium">Max Drawdown</th>
              <th className="pb-2 font-medium">Win Rate</th>
            </tr>
          </thead>
          <tbody>
            {symbols.map(s => (
              <tr key={s.symbol} className="border-b last:border-0">
                <td className="py-2 font-medium">{s.symbol}</td>
                <td className="py-2">{s.sharpeRatio?.toFixed(3) ?? '-'}</td>
                <td className="py-2">{(s.totalReturn * 100).toFixed(2)}%</td>
                <td className="py-2">{(s.maxDrawdown * 100).toFixed(1)}%</td>
                <td className="py-2">{(s.winRate * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
