import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchSymbols, backfillData, checkFeatureAvailability,
  computeFeatures, buildDataset,
  type FeatureAvailability,
} from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp,
  Loader2, Database, RefreshCw, Plus, X,
} from 'lucide-react'

interface DatasetBuilderProps {
  onClose: () => void
  onSuccess: () => void
}

type Step = 'form' | 'checking' | 'backfilling' | 'computing' | 'building' | 'done'

interface AvailabilityResult {
  [symbol: string]: FeatureAvailability
}

function generateDatasetName(symbols: string[], timeframe: string, endDate: string): string {
  const year = endDate ? endDate.slice(0, 4) : new Date().getFullYear().toString()
  const syms = symbols.slice(0, 3).join('-')
  const suffix = symbols.length > 3 ? `-+${symbols.length - 3}` : ''
  return `${syms}${suffix}-${timeframe}-${year}`
}

export function DatasetBuilder({ onClose, onSuccess }: DatasetBuilderProps) {
  const queryClient = useQueryClient()

  // Form state
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [symbolInput, setSymbolInput] = useState('')
  const [timeframe, setTimeframe] = useState<'1m' | '1d'>('1d')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [nSplits, setNSplits] = useState(5)
  const [trainFrac, setTrainFrac] = useState(0.7)
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Workflow state
  const [step, setStep] = useState<Step>('form')
  const [availability, setAvailability] = useState<AvailabilityResult | null>(null)
  const [statusMsg, setStatusMsg] = useState('')
  const [error, setError] = useState('')

  // Available symbols from DB
  const { data: availableSymbols = [] } = useQuery({
    queryKey: ['symbols'],
    queryFn: fetchSymbols,
  })

  const filteredSuggestions = symbolInput.length > 0
    ? availableSymbols.filter(
        s => s.toLowerCase().includes(symbolInput.toLowerCase()) && !selectedSymbols.includes(s)
      ).slice(0, 8)
    : []

  function addSymbol(sym: string) {
    const upper = sym.toUpperCase().trim()
    if (upper && !selectedSymbols.includes(upper)) {
      setSelectedSymbols(prev => [...prev, upper])
    }
    setSymbolInput('')
  }

  function removeSymbol(sym: string) {
    setSelectedSymbols(prev => prev.filter(s => s !== sym))
    setAvailability(null)
  }

  // Validation
  const isFormValid = selectedSymbols.length > 0 && startDate && endDate && startDate < endDate

  // Check availability + auto-backfill + build pipeline
  const backfillMut = useMutation({ mutationFn: backfillData })
  const computeMut  = useMutation({ mutationFn: computeFeatures })
  const buildMut    = useMutation({ mutationFn: buildDataset })

  async function handleCheckAvailability() {
    if (!isFormValid) return
    setError('')
    setStep('checking')
    setStatusMsg('Checking data availability...')
    try {
      const result = await checkFeatureAvailability(selectedSymbols, startDate, endDate)
      setAvailability(result)
      setStep('form')
      setStatusMsg('')
    } catch (e: any) {
      setError(e.message || 'Failed to check availability')
      setStep('form')
    }
  }

  async function handleBackfill() {
    setError('')
    setStep('backfilling')
    setStatusMsg(`Backfilling ${selectedSymbols.join(', ')} from Alpaca...`)
    try {
      await backfillMut.mutateAsync({
        symbols: selectedSymbols,
        startDate,
        endDate,
        timeframe,
      })
      setStatusMsg('Backfill started. Re-checking availability...')
      const result = await checkFeatureAvailability(selectedSymbols, startDate, endDate)
      setAvailability(result)
      setStep('form')
      setStatusMsg('')
    } catch (e: any) {
      setError(e.message || 'Backfill failed')
      setStep('form')
    }
  }

  async function handleBuild() {
    if (!isFormValid) return
    setError('')

    // Step 1: Check features
    setStep('checking')
    setStatusMsg('Checking feature availability...')
    let avail: AvailabilityResult
    try {
      avail = await checkFeatureAvailability(selectedSymbols, startDate, endDate)
      setAvailability(avail)
    } catch (e: any) {
      setError(e.message || 'Failed to check features')
      setStep('form')
      return
    }

    // Step 2: Auto-compute missing features
    const needsCompute = selectedSymbols.some(
      sym => (avail[sym]?.feature_rows ?? 0) < (avail[sym]?.bar_rows ?? 0) * 0.5
    )
    if (needsCompute) {
      setStep('computing')
      setStatusMsg('Computing missing features (RSI, MACD, ATR, etc.)...')
      try {
        await computeMut.mutateAsync({ symbols: selectedSymbols, start_date: startDate, end_date: endDate })
      } catch (e: any) {
        setError(e.message || 'Feature computation failed')
        setStep('form')
        return
      }
    }

    // Step 2.5: Block if any symbol has zero bars — user must backfill first
    const missingBars = selectedSymbols.filter(sym => (avail[sym]?.bar_rows ?? 0) === 0)
    if (missingBars.length > 0) {
      setError(
        `No bar data found for: ${missingBars.join(', ')}. ` +
        `Use "Check Data" then "Backfill Missing Data" before building.`
      )
      setStep('form')
      return
    }

    // Step 3: Build dataset
    setStep('building')
    const name = generateDatasetName(selectedSymbols, timeframe, endDate)
    setStatusMsg(`Building dataset "${name}"...`)
    try {
      await buildMut.mutateAsync({
        name,
        symbols: selectedSymbols,
        start_date: startDate,
        end_date: endDate,
        n_splits: nSplits,
        train_frac: trainFrac,
      })
      setStep('done')
      setStatusMsg(`Dataset "${name}" created successfully!`)
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      setTimeout(onSuccess, 1500)
    } catch (e: any) {
      setError(e.message || 'Dataset build failed')
      setStep('form')
    }
  }

  const isWorking = ['checking', 'backfilling', 'computing', 'building'].includes(step)
  const needsBackfill = availability && selectedSymbols.some(
    sym => (availability[sym]?.bar_rows ?? 0) === 0
  )

  return (
    <Card className="border-primary/30">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <Database className="h-5 w-5 text-primary" />
            Build New Dataset
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isWorking}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">

        {/* Symbol selector */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Symbols</label>
          <div className="relative">
            <div className="flex flex-wrap gap-1 mb-2">
              {selectedSymbols.map(sym => (
                <span key={sym} className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
                  {sym}
                  <button onClick={() => removeSymbol(sym)} disabled={isWorking}
                    className="hover:text-destructive transition-colors">
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  placeholder="Type symbol (e.g. AAPL) and press Enter…"
                  value={symbolInput}
                  disabled={isWorking}
                  onChange={e => setSymbolInput(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && symbolInput.trim()) {
                      e.preventDefault()
                      addSymbol(symbolInput)
                    }
                  }}
                />
                {filteredSuggestions.length > 0 && (
                  <div className="absolute top-full left-0 right-0 z-10 mt-1 rounded-md border bg-popover shadow-md">
                    {filteredSuggestions.map(sym => (
                      <button key={sym} onClick={() => addSymbol(sym)}
                        className="w-full px-3 py-2 text-left text-sm hover:bg-accent transition-colors">
                        {sym}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <Button variant="outline" size="sm" disabled={!symbolInput.trim() || isWorking}
                onClick={() => addSymbol(symbolInput)}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Timeframe */}
        <div className="space-y-2">
          <label className="text-sm font-medium">Timeframe</label>
          <div className="flex gap-2">
            {(['1d', '1m'] as const).map(tf => (
              <button key={tf}
                onClick={() => { setTimeframe(tf); setAvailability(null) }}
                disabled={isWorking}
                className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                  timeframe === tf
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-input hover:bg-accent'
                }`}>
                {tf === '1d' ? '1 Day' : '1 Minute'}
              </button>
            ))}
          </div>
        </div>

        {/* Date range */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <label className="text-sm font-medium">Start Date</label>
            <Input type="date" value={startDate} disabled={isWorking}
              onChange={e => { setStartDate(e.target.value); setAvailability(null) }} />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">End Date</label>
            <Input type="date" value={endDate} disabled={isWorking}
              onChange={e => { setEndDate(e.target.value); setAvailability(null) }} />
          </div>
        </div>

        {/* Advanced options */}
        <div className="border rounded-md">
          <button onClick={() => setShowAdvanced(v => !v)} disabled={isWorking}
            className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium hover:bg-accent transition-colors rounded-md">
            Advanced Options
            {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {showAdvanced && (
            <div className="grid grid-cols-2 gap-3 px-3 pb-3">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Walk-Forward Splits
                  <span className="ml-1 text-muted-foreground/60">(how many train/test pairs)</span>
                </label>
                <Input type="number" min={2} max={20} value={nSplits} disabled={isWorking}
                  onChange={e => setNSplits(Number(e.target.value))} />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Train Fraction
                  <span className="ml-1 text-muted-foreground/60">(0.6–0.9)</span>
                </label>
                <Input type="number" min={0.5} max={0.95} step={0.05} value={trainFrac} disabled={isWorking}
                  onChange={e => setTrainFrac(Number(e.target.value))} />
              </div>
            </div>
          )}
        </div>

        {/* Data availability results */}
        {availability && (
          <div className="rounded-md border bg-muted/30 p-3 space-y-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Data Availability</p>
            {selectedSymbols.map(sym => {
              const a = availability[sym]
              if (!a) return null
              const featPct = a.bar_rows > 0 ? Math.round(a.feature_rows / a.bar_rows * 100) : 0
              const hasData = a.bar_rows > 0
              const hasFeatures = featPct >= 80
              return (
                <div key={sym} className="flex items-center gap-3 text-sm">
                  {hasData && hasFeatures
                    ? <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                    : hasData
                    ? <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0" />
                    : <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                  }
                  <span className="font-medium w-16">{sym}</span>
                  <span className="text-muted-foreground">
                    {a.bar_rows} bars · {a.feature_rows} features ({featPct}%)
                  </span>
                  {!hasData && <span className="text-xs text-red-500">No data — backfill needed</span>}
                  {hasData && !hasFeatures && <span className="text-xs text-amber-500">Features will be computed</span>}
                </div>
              )
            })}
          </div>
        )}

        {/* Status / error messages */}
        {statusMsg && (
          <div className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm ${
            step === 'done' ? 'bg-green-500/10 text-green-700' : 'bg-blue-500/10 text-blue-700'
          }`}>
            {step === 'done'
              ? <CheckCircle2 className="h-4 w-4" />
              : <Loader2 className="h-4 w-4 animate-spin" />
            }
            {statusMsg}
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <XCircle className="h-4 w-4" />
            {error}
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 pt-1">
          <Button variant="outline" size="sm" disabled={!isFormValid || isWorking}
            onClick={handleCheckAvailability} className="gap-1.5">
            {step === 'checking'
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <RefreshCw className="h-4 w-4" />
            }
            Check Data
          </Button>

          {needsBackfill && (
            <Button variant="outline" size="sm" disabled={isWorking}
              onClick={handleBackfill} className="gap-1.5 border-amber-500 text-amber-600 hover:bg-amber-50">
              {step === 'backfilling'
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : <RefreshCw className="h-4 w-4" />
              }
              Backfill Missing Data
            </Button>
          )}

          <Button size="sm" disabled={!isFormValid || isWorking} onClick={handleBuild}
            className="ml-auto gap-1.5">
            {isWorking && step !== 'checking'
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <Database className="h-4 w-4" />
            }
            Build Dataset
          </Button>
        </div>

      </CardContent>
    </Card>
  )
}
