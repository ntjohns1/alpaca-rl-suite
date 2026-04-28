import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchJobs, startTraining, cancelJob, fetchQuota, type KaggleJob } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/StatusBadge'
import { Plus, X, Cpu } from 'lucide-react'

export function Training() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)

  const { data: jobs = [], isLoading } = useQuery({ queryKey: ['jobs'], queryFn: () => fetchJobs(), refetchInterval: 30_000 })
  const { data: quota } = useQuery({ queryKey: ['quota'], queryFn: fetchQuota })

  const trainMutation = useMutation({
    mutationFn: startTraining,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['jobs'] }); setShowForm(false) },
  })

  const cancelMutation = useMutation({
    mutationFn: cancelJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Training</h1>
        <div className="flex items-center gap-3">
          {quota && !quota.error && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Cpu className="h-4 w-4" />
              GPU: {quota.gpuRemaining ?? '?'}h remaining
            </div>
          )}
          <Button onClick={() => setShowForm(!showForm)}>
            <Plus className="mr-2 h-4 w-4" /> New Training Job
          </Button>
        </div>
      </div>

      {showForm && <TrainingForm onSubmit={(p) => trainMutation.mutate(p)} isPending={trainMutation.isPending} />}

      <Card>
        <CardHeader><CardTitle className="text-lg">Training Jobs</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No training jobs yet. Start one above.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Name</th>
                    <th className="pb-2 font-medium">Status</th>
                    <th className="pb-2 font-medium">Approval</th>
                    <th className="pb-2 font-medium">Created</th>
                    <th className="pb-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job: KaggleJob) => (
                    <tr key={job.id} className="border-b last:border-0">
                      <td className="py-3 font-medium">{job.name}</td>
                      <td className="py-3"><StatusBadge status={job.status} /></td>
                      <td className="py-3"><StatusBadge status={job.approval_status} /></td>
                      <td className="py-3 text-muted-foreground">{new Date(job.created_at).toLocaleDateString()}</td>
                      <td className="py-3">
                        {!['completed', 'failed', 'cancelled', 'pending_approval'].includes(job.status) && (
                          <Button variant="ghost" size="sm" onClick={() => cancelMutation.mutate(job.id)}>
                            <X className="mr-1 h-3 w-3" /> Cancel
                          </Button>
                        )}
                      </td>
                    </tr>
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

function TrainingForm({ onSubmit, isPending }: { onSubmit: (p: Parameters<typeof startTraining>[0]) => void; isPending: boolean }) {
  const [name, setName] = useState('')
  const [symbol, setSymbol] = useState('SPY')
  const [timesteps, setTimesteps] = useState(500000)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({ name: name || `${symbol}-${Date.now()}`, symbols: [symbol], totalTimesteps: timesteps })
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-lg">New Training Job</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid gap-4 sm:grid-cols-4">
          <div>
            <label className="mb-1 block text-sm font-medium">Name</label>
            <input className="w-full rounded-md border px-3 py-2 text-sm" placeholder="e.g. SPY-experiment-1"
              value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Symbol</label>
            <input className="w-full rounded-md border px-3 py-2 text-sm" value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())} required />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Timesteps</label>
            <input className="w-full rounded-md border px-3 py-2 text-sm" type="number" value={timesteps}
              onChange={(e) => setTimesteps(Number(e.target.value))} min={10000} step={50000} />
          </div>
          <div className="flex items-end">
            <Button type="submit" disabled={isPending} className="w-full">
              {isPending ? 'Submitting...' : 'Start Training'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
