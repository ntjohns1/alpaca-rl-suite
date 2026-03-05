import { useQuery } from '@tanstack/react-query'
import { fetchConfig, fetchServices } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/StatusBadge'
import { ExternalLink, RefreshCw } from 'lucide-react'

export function Monitoring() {
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: fetchConfig })
  const { data: health, refetch, isFetching } = useQuery({ queryKey: ['services'], queryFn: fetchServices })

  const grafanaUrl = config?.grafanaUrl || 'http://localhost:3100'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Monitoring</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={grafanaUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-2 h-4 w-4" /> Open Grafana
            </a>
          </Button>
        </div>
      </div>

      {/* Service Health */}
      <Card>
        <CardHeader><CardTitle className="text-lg">Service Health</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {health?.services?.map((s) => (
              <div key={s.service} className="flex items-center justify-between rounded-lg border p-4">
                <div>
                  <p className="font-medium">{s.service}</p>
                  <p className="text-xs text-muted-foreground">
                    {s.status === 'ok' ? `Latency: ${s.latencyMs}ms` : s.error || s.status}
                  </p>
                </div>
                <StatusBadge status={s.status} />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Embedded Grafana */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Grafana Dashboard</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-lg border">
            <iframe
              src={`${grafanaUrl}/d/alpaca-rl-overview?orgId=1&kiosk`}
              className="h-[600px] w-full border-0"
              title="Grafana Dashboard"
            />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            If the dashboard doesn't load, ensure Grafana is running and accessible at{' '}
            <a href={grafanaUrl} target="_blank" rel="noopener noreferrer" className="text-primary underline">
              {grafanaUrl}
            </a>.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
