import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchJobs, cancelJob, type KaggleJob } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/StatusBadge'
import { X } from 'lucide-react'

export function Training() {
  const queryClient = useQueryClient()

  const { data: jobs = [], isLoading } = useQuery({ queryKey: ['jobs'], queryFn: () => fetchJobs(), refetchInterval: 30_000 })

  const cancelMutation = useMutation({
    mutationFn: cancelJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Training</h1>
          <p className="text-muted-foreground">View and manage Kaggle training jobs.</p>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-lg">Training Jobs</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : jobs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No training jobs yet.</p>
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
