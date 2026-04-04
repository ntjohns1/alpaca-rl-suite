import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDatasets, deleteDataset, type Dataset } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { DatasetBuilder } from '@/components/DatasetBuilder'
import { Trash2, Database, Plus } from 'lucide-react'

export function Datasets() {
  const queryClient = useQueryClient()
  const [showBuilder, setShowBuilder] = useState(false)

  const { data: datasets = [], isLoading } = useQuery({ queryKey: ['datasets'], queryFn: fetchDatasets })

  const deleteMut = useMutation({
    mutationFn: deleteDataset,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['datasets'] }),
  })

  if (isLoading) return <div className="flex items-center justify-center py-20 text-muted-foreground">Loading...</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Datasets</h1>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Database className="h-4 w-4" /> {datasets.length} datasets
          </span>
          {!showBuilder && (
            <Button size="sm" onClick={() => setShowBuilder(true)} className="gap-1.5">
              <Plus className="h-4 w-4" /> Build New Dataset
            </Button>
          )}
        </div>
      </div>

      {showBuilder && (
        <DatasetBuilder
          onClose={() => setShowBuilder(false)}
          onSuccess={() => setShowBuilder(false)}
        />
      )}

      <Card>
        <CardHeader><CardTitle className="text-lg">Dataset Manifests</CardTitle></CardHeader>
        <CardContent>
          {datasets.length === 0 ? (
            <div className="py-8 text-center space-y-3">
              <Database className="h-10 w-10 mx-auto text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No datasets yet.</p>
              {!showBuilder && (
                <Button size="sm" variant="outline" onClick={() => setShowBuilder(true)} className="gap-1.5">
                  <Plus className="h-4 w-4" /> Build your first dataset
                </Button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Name</th>
                    <th className="pb-2 font-medium">Symbols</th>
                    <th className="pb-2 font-medium">Date Range</th>
                    <th className="pb-2 font-medium">Splits</th>
                    <th className="pb-2 font-medium">Created</th>
                    <th className="pb-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((ds: Dataset) => (
                    <tr key={ds.id} className="border-b last:border-0">
                      <td className="py-3 font-medium">{ds.name}</td>
                      <td className="py-3 text-muted-foreground">
                        {Array.isArray(ds.symbols) ? ds.symbols.join(', ') : String(ds.symbols)}
                      </td>
                      <td className="py-3 text-muted-foreground">{ds.start_date} → {ds.end_date}</td>
                      <td className="py-3 text-muted-foreground">{ds.n_splits}</td>
                      <td className="py-3 text-muted-foreground">{new Date(ds.created_at).toLocaleDateString()}</td>
                      <td className="py-3">
                        <Button variant="ghost" size="sm"
                          onClick={() => { if (confirm('Delete this dataset?')) deleteMut.mutate(ds.id) }}>
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
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
