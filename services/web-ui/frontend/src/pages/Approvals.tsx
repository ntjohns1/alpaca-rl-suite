import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchJobs, approveJob, rejectJob, type KaggleJob } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/StatusBadge'
import { CheckCircle2, XCircle, Clock, TrendingUp, TrendingDown, Target, BarChart3 } from 'lucide-react'

export function Approvals() {
  const queryClient = useQueryClient()
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs', 'pending_approval'],
    queryFn: () => fetchJobs('pending_approval'),
  })

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectJob(id, 'Rejected via UI'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  if (isLoading) return <div className="flex items-center justify-center py-20 text-muted-foreground">Loading...</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Approvals</h1>
          <p className="text-muted-foreground">Review completed training jobs before promoting to production.</p>
        </div>
        {jobs.length > 0 && (
          <span className="inline-flex h-8 items-center rounded-full bg-amber-100 px-3 text-sm font-semibold text-amber-800">
            {jobs.length} pending
          </span>
        )}
      </div>

      {jobs.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <CheckCircle2 className="mb-4 h-12 w-12 text-green-400" />
            <p className="text-lg font-medium">All caught up!</p>
            <p className="text-sm text-muted-foreground">No jobs pending approval.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {jobs.map((job: KaggleJob) => (
            <ApprovalCard
              key={job.id}
              job={job}
              onApprove={() => approveMutation.mutate(job.id)}
              onReject={() => rejectMutation.mutate(job.id)}
              isApproving={approveMutation.isPending}
              isRejecting={rejectMutation.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ApprovalCard({ job, onApprove, onReject, isApproving, isRejecting }: {
  job: KaggleJob; onApprove: () => void; onReject: () => void; isApproving: boolean; isRejecting: boolean
}) {
  const meta = job.metadata || {}
  const metrics = (meta as Record<string, unknown>).backtest_metrics as Record<string, number> | undefined

  return (
    <Card className="border-amber-200">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">{job.name}</CardTitle>
            <CardDescription className="flex items-center gap-2">
              <Clock className="h-3 w-3" />
              Completed {job.completed_at ? new Date(job.completed_at).toLocaleString() : 'recently'}
            </CardDescription>
          </div>
          <StatusBadge status={job.approval_status} />
        </div>
      </CardHeader>
      <CardContent>
        {metrics ? (
          <div className="grid gap-4 sm:grid-cols-4">
            <MetricCard label="Sharpe Ratio" value={metrics.avgSharpe?.toFixed(3) ?? '-'} icon={TrendingUp}
              pass={metrics.avgSharpe != null && metrics.avgSharpe > 1.0} />
            <MetricCard label="Max Drawdown" value={metrics.avgMaxDrawdown != null ? `${(metrics.avgMaxDrawdown * 100).toFixed(1)}%` : '-'} icon={TrendingDown}
              pass={metrics.avgMaxDrawdown != null && metrics.avgMaxDrawdown < 0.15} />
            <MetricCard label="Win Rate" value={metrics.avgWinRate != null ? `${(metrics.avgWinRate * 100).toFixed(1)}%` : '-'} icon={Target}
              pass={metrics.avgWinRate != null && metrics.avgWinRate > 0.5} />
            <MetricCard label="Total Return" value={metrics.avgTotalReturn != null ? `${(metrics.avgTotalReturn * 100).toFixed(2)}%` : '-'} icon={BarChart3}
              pass={metrics.avgTotalReturn != null && metrics.avgTotalReturn > 0} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No backtest metrics available for this job.</p>
        )}
      </CardContent>
      <CardFooter className="gap-3 border-t pt-4">
        <Button onClick={onApprove} disabled={isApproving} className="bg-green-600 hover:bg-green-700">
          <CheckCircle2 className="mr-2 h-4 w-4" />
          {isApproving ? 'Approving...' : 'Approve & Promote'}
        </Button>
        <Button variant="destructive" onClick={onReject} disabled={isRejecting}>
          <XCircle className="mr-2 h-4 w-4" />
          {isRejecting ? 'Rejecting...' : 'Reject'}
        </Button>
      </CardFooter>
    </Card>
  )
}

function MetricCard({ label, value, icon: Icon, pass }: {
  label: string; value: string; icon: React.ComponentType<{ className?: string }>; pass: boolean
}) {
  return (
    <div className={`rounded-lg border p-3 ${pass ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-xl font-bold">{value}</span>
        {pass
          ? <CheckCircle2 className="h-4 w-4 text-green-600" />
          : <XCircle className="h-4 w-4 text-red-500" />}
      </div>
    </div>
  )
}
