import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchPolicies, promotePolicy, deletePolicy, approvePolicy, rejectPolicy, type Policy } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/StatusBadge'
import { Trash2, ArrowUpCircle, CheckCircle2, XCircle } from 'lucide-react'

export function Policies() {
  const queryClient = useQueryClient()
  const { data: policies = [], isLoading } = useQuery({ queryKey: ['policies'], queryFn: () => fetchPolicies() })

  const promoteMut  = useMutation({ mutationFn: promotePolicy,  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['policies'] }) })
  const deleteMut   = useMutation({ mutationFn: deletePolicy,   onSuccess: () => queryClient.invalidateQueries({ queryKey: ['policies'] }) })
  const approveMut  = useMutation({ mutationFn: approvePolicy,  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['policies'] }) })
  const rejectMut   = useMutation({ mutationFn: (id: string) => rejectPolicy(id, 'Rejected via UI'), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['policies'] }) })

  if (isLoading) return <div className="flex items-center justify-center py-20 text-muted-foreground">Loading...</div>

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight">Policies</h1>

      <Card>
        <CardHeader><CardTitle className="text-lg">Policy Bundles ({policies.length})</CardTitle></CardHeader>
        <CardContent>
          {policies.length === 0 ? (
            <p className="text-sm text-muted-foreground">No policies found.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Name</th>
                    <th className="pb-2 font-medium">Version</th>
                    <th className="pb-2 font-medium">Approval</th>
                    <th className="pb-2 font-medium">Promoted</th>
                    <th className="pb-2 font-medium">Created</th>
                    <th className="pb-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {policies.map((p: Policy) => (
                    <tr key={p.id} className="border-b last:border-0">
                      <td className="py-3 font-medium">{p.name}</td>
                      <td className="py-3 text-muted-foreground">{p.version}</td>
                      <td className="py-3"><StatusBadge status={p.approval_status || 'pending'} /></td>
                      <td className="py-3">
                        {p.promoted
                          ? <span className="text-green-600 font-medium">Yes</span>
                          : <span className="text-muted-foreground">No</span>}
                      </td>
                      <td className="py-3 text-muted-foreground">{new Date(p.created_at).toLocaleDateString()}</td>
                      <td className="py-3">
                        <div className="flex gap-1">
                          {p.approval_status === 'pending' && (
                            <>
                              <Button variant="ghost" size="sm" onClick={() => approveMut.mutate(p.id)} title="Approve">
                                <CheckCircle2 className="h-4 w-4 text-green-600" />
                              </Button>
                              <Button variant="ghost" size="sm" onClick={() => rejectMut.mutate(p.id)} title="Reject">
                                <XCircle className="h-4 w-4 text-red-500" />
                              </Button>
                            </>
                          )}
                          {p.approval_status === 'approved' && !p.promoted && (
                            <Button variant="ghost" size="sm" onClick={() => promoteMut.mutate(p.id)} title="Promote">
                              <ArrowUpCircle className="h-4 w-4 text-blue-600" />
                            </Button>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => { if (confirm('Delete this policy?')) deleteMut.mutate(p.id) }} title="Delete">
                            <Trash2 className="h-4 w-4 text-red-500" />
                          </Button>
                        </div>
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
