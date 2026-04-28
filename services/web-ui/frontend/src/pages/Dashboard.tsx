import { useQuery } from '@tanstack/react-query'
import { fetchOverview, fetchActivity } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/StatusBadge'
import {
  CheckCircle2, XCircle, Clock, Brain, BarChart3, AlertTriangle, Activity,
} from 'lucide-react'

export function Dashboard() {
  const { data: overview, isLoading } = useQuery({ queryKey: ['overview'], queryFn: fetchOverview, refetchInterval: 30_000 })
  const { data: activity } = useQuery({ queryKey: ['activity'], queryFn: () => fetchActivity(10), refetchInterval: 30_000 })

  if (isLoading) return <div className="flex items-center justify-center py-20 text-muted-foreground">Loading...</div>

  const stats = overview?.stats
  const services = overview?.services || []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <StatusBadge status={overview?.systemStatus || 'unknown'} />
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Training Jobs" value={stats?.totalTrainingJobs ?? 0} icon={Activity}
                  sub={`${stats?.completedJobs ?? 0} completed · ${stats?.failedJobs ?? 0} failed`} />
        <StatCard title="Pending Approvals" value={stats?.pendingApprovals ?? 0} icon={AlertTriangle}
                  sub="Awaiting review" highlight={!!stats?.pendingApprovals} />
        <StatCard title="Promoted Policies" value={stats?.promotedPolicies ?? 0} icon={Brain}
                  sub="In production" />
        <StatCard title="Backtests" value={stats?.totalBacktests ?? 0} icon={BarChart3}
                  sub={`${stats?.completedBacktests ?? 0} completed`} />
      </div>

      {/* Services Health */}
      <Card>
        <CardHeader><CardTitle className="text-lg">Service Health</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {services.map((s) => (
              <div key={s.service} className="flex items-center gap-3 rounded-lg border p-3">
                {s.status === 'ok'
                  ? <CheckCircle2 className="h-5 w-5 text-green-500" />
                  : <XCircle className="h-5 w-5 text-red-500" />}
                <div>
                  <p className="text-sm font-medium">{s.service}</p>
                  <p className="text-xs text-muted-foreground">
                    {s.status === 'ok' ? `${s.latencyMs}ms` : s.status}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Recent Activity */}
      <Card>
        <CardHeader><CardTitle className="text-lg">Recent Activity</CardTitle></CardHeader>
        <CardContent>
          {activity?.events?.length ? (
            <div className="space-y-3">
              {activity.events.map((ev) => (
                <div key={`${ev.type}-${ev.id}`} className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-3">
                    <Clock className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium">{ev.name}</p>
                      <p className="text-xs text-muted-foreground">{ev.type} · {new Date(ev.timestamp).toLocaleString()}</p>
                    </div>
                  </div>
                  <StatusBadge status={ev.status} />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No recent activity</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function StatCard({ title, value, icon: Icon, sub, highlight }: {
  title: string; value: number; icon: React.ComponentType<{ className?: string }>; sub: string; highlight?: boolean
}) {
  return (
    <Card className={highlight ? 'border-amber-300 bg-amber-50' : ''}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <p className="text-xs text-muted-foreground">{sub}</p>
      </CardContent>
    </Card>
  )
}
