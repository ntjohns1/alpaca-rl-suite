import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchDatasets, deleteDataset, fetchKaggleDatasets, uploadToKaggle,
  type Dataset, type KaggleDataset,
} from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { DatasetBuilder } from '@/components/DatasetBuilder'
import {
  Trash2, Database, Plus, Upload, ExternalLink, Loader2,
  CheckCircle2, Globe, Lock,
} from 'lucide-react'

export function Datasets() {
  const queryClient = useQueryClient()
  const [showBuilder, setShowBuilder] = useState(false)
  const [uploadingSymbol, setUploadingSymbol] = useState<string | null>(null)

  const { data: datasets = [], isLoading } = useQuery({ queryKey: ['datasets'], queryFn: fetchDatasets })
  const { data: kaggleData, isLoading: kaggleLoading } = useQuery({
    queryKey: ['kaggle-datasets'],
    queryFn: fetchKaggleDatasets,
    refetchInterval: 60_000,
  })

  const deleteMut = useMutation({
    mutationFn: deleteDataset,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['datasets'] }),
  })

  const uploadMut = useMutation({
    mutationFn: ({ symbol, slug }: { symbol: string; slug?: string }) => uploadToKaggle(symbol, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kaggle-datasets'] })
      setUploadingSymbol(null)
    },
    onError: () => setUploadingSymbol(null),
  })

  function handleUploadToKaggle(ds: Dataset) {
    const symbol = Array.isArray(ds.symbols) ? ds.symbols[0] : ds.symbols
    setUploadingSymbol(symbol)
    uploadMut.mutate({ symbol })
  }

  if (isLoading) return <div className="flex items-center justify-center py-20 text-muted-foreground">Loading...</div>

  const kaggleDatasets = kaggleData?.datasets ?? []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight">Datasets</h1>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Database className="h-4 w-4" /> {datasets.length} local
          </span>
          {kaggleDatasets.length > 0 && (
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Globe className="h-4 w-4" /> {kaggleDatasets.length} on Kaggle
            </span>
          )}
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

      {/* Upload error banner */}
      {uploadMut.isError && (
        <div className="rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Upload failed: {(uploadMut.error as Error)?.message || 'Unknown error'}
        </div>
      )}

      {/* Upload success banner */}
      {uploadMut.isSuccess && (
        <div className="flex items-center gap-2 rounded-md bg-green-500/10 px-4 py-3 text-sm text-green-700">
          <CheckCircle2 className="h-4 w-4" />
          Dataset uploaded to Kaggle successfully!
          {uploadMut.data?.kaggleUrl && (
            <a href={uploadMut.data.kaggleUrl} target="_blank" rel="noopener noreferrer"
              className="ml-1 inline-flex items-center gap-1 underline hover:no-underline">
              View on Kaggle <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}

      {/* Local Dataset Manifests */}
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
                  {datasets.map((ds: Dataset) => {
                    const symbol = Array.isArray(ds.symbols) ? ds.symbols[0] : ds.symbols
                    const isUploading = uploadingSymbol === symbol && uploadMut.isPending
                    return (
                      <tr key={ds.id} className="border-b last:border-0">
                        <td className="py-3 font-medium">{ds.name}</td>
                        <td className="py-3 text-muted-foreground">
                          {Array.isArray(ds.symbols) ? ds.symbols.join(', ') : String(ds.symbols)}
                        </td>
                        <td className="py-3 text-muted-foreground">{ds.start_date} &rarr; {ds.end_date}</td>
                        <td className="py-3 text-muted-foreground">{ds.n_splits}</td>
                        <td className="py-3 text-muted-foreground">{new Date(ds.created_at).toLocaleDateString()}</td>
                        <td className="py-3">
                          <div className="flex items-center gap-1">
                            <Button variant="ghost" size="sm" title="Upload to Kaggle"
                              disabled={isUploading}
                              onClick={() => handleUploadToKaggle(ds)}>
                              {isUploading
                                ? <Loader2 className="h-4 w-4 animate-spin" />
                                : <Upload className="h-4 w-4 text-blue-500" />
                              }
                            </Button>
                            <Button variant="ghost" size="sm" title="Delete dataset"
                              onClick={() => { if (confirm('Delete this dataset?')) deleteMut.mutate(ds.id) }}>
                              <Trash2 className="h-4 w-4 text-red-500" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Kaggle Datasets */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Globe className="h-5 w-5" />
            Kaggle Datasets
          </CardTitle>
        </CardHeader>
        <CardContent>
          {kaggleLoading ? (
            <div className="flex items-center gap-2 py-8 justify-center text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading Kaggle datasets...
            </div>
          ) : kaggleDatasets.length === 0 ? (
            <div className="py-8 text-center space-y-2">
              <Globe className="h-10 w-10 mx-auto text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No datasets on Kaggle yet.</p>
              <p className="text-xs text-muted-foreground">Upload a local dataset using the upload button above.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Title</th>
                    <th className="pb-2 font-medium">Slug</th>
                    <th className="pb-2 font-medium">Size</th>
                    <th className="pb-2 font-medium">Version</th>
                    <th className="pb-2 font-medium">Last Updated</th>
                    <th className="pb-2 font-medium">Visibility</th>
                    <th className="pb-2 font-medium">Link</th>
                  </tr>
                </thead>
                <tbody>
                  {kaggleDatasets.map((kds: KaggleDataset) => (
                    <KaggleDatasetRow key={kds.id} dataset={kds} />
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

function formatBytes(bytes: number | null): string {
  if (bytes == null || bytes === 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(i > 0 ? 1 : 0)} ${units[i]}`
}

function KaggleDatasetRow({ dataset }: { dataset: KaggleDataset }) {
  const kaggleUrl = dataset.url
    ? (dataset.url.startsWith('http') ? dataset.url : `https://www.kaggle.com${dataset.url}`)
    : null

  return (
    <tr className="border-b last:border-0">
      <td className="py-3 font-medium">{dataset.title}</td>
      <td className="py-3 text-muted-foreground font-mono text-xs">{dataset.slug}</td>
      <td className="py-3 text-muted-foreground">{formatBytes(dataset.totalBytes)}</td>
      <td className="py-3 text-muted-foreground">v{dataset.currentVersionNumber}</td>
      <td className="py-3 text-muted-foreground">
        {dataset.lastUpdated ? new Date(dataset.lastUpdated).toLocaleDateString() : '-'}
      </td>
      <td className="py-3">
        {dataset.isPrivate
          ? <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Lock className="h-3 w-3" /> Private</span>
          : <span className="inline-flex items-center gap-1 text-xs text-green-600"><Globe className="h-3 w-3" /> Public</span>
        }
      </td>
      <td className="py-3">
        {kaggleUrl && (
          <a href={kaggleUrl} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-blue-500 hover:text-blue-700 transition-colors">
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
      </td>
    </tr>
  )
}
