import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchJobs, cancelJob, downloadModel, type KaggleJob, type ModelDownloadResponse } from '@/api/client'
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StatusBadge } from '@/components/StatusBadge'
import {
  X, ExternalLink, Download, Loader2, CheckCircle2,
  XCircle, Package,
} from 'lucide-react'

const KAGGLE_USERNAME = 'nelsonjohns'
const DEFAULT_KERNEL_SLUG = 'alpaca-rl-training'

export function Training() {
  const queryClient = useQueryClient()
  const [showDownloadModal, setShowDownloadModal] = useState(false)

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => fetchJobs(),
    refetchInterval: 30_000,
  })

  const cancelMutation = useMutation({
    mutationFn: cancelJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })

  const kaggleKernelUrl = `https://www.kaggle.com/code/${KAGGLE_USERNAME}/${DEFAULT_KERNEL_SLUG}`

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Training</h1>
          <p className="text-muted-foreground">View training jobs and download models from Kaggle.</p>
        </div>
        <div className="flex items-center gap-3">
          <a href={kaggleKernelUrl} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" className="gap-1.5">
              <ExternalLink className="h-4 w-4" />
              Open Kaggle Kernel
            </Button>
          </a>
          <Button size="sm" onClick={() => setShowDownloadModal(true)} className="gap-1.5">
            <Download className="h-4 w-4" />
            Download Model
          </Button>
        </div>
      </div>

      {showDownloadModal && (
        <ModelDownloadModal onClose={() => setShowDownloadModal(false)} />
      )}

      <Card>
        <CardHeader><CardTitle className="text-lg">Training Jobs</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : jobs.length === 0 ? (
            <div className="py-8 text-center space-y-3">
              <Package className="h-10 w-10 mx-auto text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No training jobs yet.</p>
              <p className="text-xs text-muted-foreground">
                Run training on{' '}
                <a href={kaggleKernelUrl} target="_blank" rel="noopener noreferrer"
                  className="text-blue-500 hover:underline">
                  Kaggle
                </a>
                , then download the model here.
              </p>
            </div>
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
                    <JobRow
                      key={job.id}
                      job={job}
                      onCancel={() => cancelMutation.mutate(job.id)}
                      isCancelling={cancelMutation.isPending}
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

function JobRow({ job, onCancel, isCancelling }: {
  job: KaggleJob
  onCancel: () => void
  isCancelling: boolean
}) {
  const meta = (job.metadata || {}) as Record<string, unknown>
  const kaggleUrl = meta.kaggle_url as string | undefined

  const isActive = !['completed', 'failed', 'cancelled', 'pending_approval'].includes(job.status)

  return (
    <tr className="border-b last:border-0">
      <td className="py-3 font-medium">{job.name}</td>
      <td className="py-3"><StatusBadge status={job.status} /></td>
      <td className="py-3"><StatusBadge status={job.approval_status} /></td>
      <td className="py-3 text-muted-foreground">{new Date(job.created_at).toLocaleDateString()}</td>
      <td className="py-3">
        <div className="flex items-center gap-1">
          {kaggleUrl && (
            <a href={kaggleUrl} target="_blank" rel="noopener noreferrer" title="View on Kaggle">
              <Button variant="ghost" size="sm">
                <ExternalLink className="h-4 w-4 text-blue-500" />
              </Button>
            </a>
          )}
          {isActive && (
            <Button variant="ghost" size="sm" onClick={onCancel} disabled={isCancelling}
              title="Cancel job">
              <X className="mr-1 h-3 w-3" /> Cancel
            </Button>
          )}
        </div>
      </td>
    </tr>
  )
}

function ModelDownloadModal({ onClose }: { onClose: () => void }) {
  const [kernelSlug, setKernelSlug] = useState(DEFAULT_KERNEL_SLUG)

  const downloadMut = useMutation({
    mutationFn: (slug: string) => downloadModel(slug),
  })

  const handleDownload = (e: React.FormEvent) => {
    e.preventDefault()
    if (kernelSlug.trim()) {
      downloadMut.mutate(kernelSlug.trim())
    }
  }

  const result = downloadMut.data as ModelDownloadResponse | undefined

  return (
    <Card className="border-primary/30">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg flex items-center gap-2">
              <Download className="h-5 w-5 text-primary" />
              Download Model from Kaggle
            </CardTitle>
            <CardDescription>
              Download a trained model from Kaggle notebook output and upload it to MinIO.
            </CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={downloadMut.isPending}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleDownload} className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Kernel Slug</label>
            <div className="flex gap-2">
              <Input
                placeholder="e.g. alpaca-rl-training"
                value={kernelSlug}
                onChange={(e) => setKernelSlug(e.target.value)}
                disabled={downloadMut.isPending}
              />
              <Button type="submit" disabled={!kernelSlug.trim() || downloadMut.isPending}
                className="gap-1.5 shrink-0">
                {downloadMut.isPending
                  ? <><Loader2 className="h-4 w-4 animate-spin" /> Downloading...</>
                  : <><Download className="h-4 w-4" /> Download</>
                }
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              The notebook at{' '}
              <a href={`https://www.kaggle.com/code/${KAGGLE_USERNAME}/${kernelSlug || DEFAULT_KERNEL_SLUG}`}
                target="_blank" rel="noopener noreferrer"
                className="text-blue-500 hover:underline inline-flex items-center gap-0.5">
                kaggle.com/code/{KAGGLE_USERNAME}/{kernelSlug || DEFAULT_KERNEL_SLUG}
                <ExternalLink className="h-3 w-3" />
              </a>
            </p>
          </div>

          {/* Progress / result */}
          {downloadMut.isPending && (
            <div className="flex items-center gap-2 rounded-md bg-blue-500/10 px-3 py-2 text-sm text-blue-700">
              <Loader2 className="h-4 w-4 animate-spin" />
              Downloading model from Kaggle and uploading to MinIO...
            </div>
          )}

          {downloadMut.isSuccess && result && (
            <div className="rounded-md bg-green-500/10 px-3 py-3 space-y-2">
              <div className="flex items-center gap-2 text-sm text-green-700">
                <CheckCircle2 className="h-4 w-4" />
                Model downloaded and uploaded to MinIO successfully!
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div><span className="font-medium">File:</span> {result.modelFile}</div>
                <div><span className="font-medium">S3 Path:</span> <code className="bg-muted px-1 rounded">{result.s3Path}</code></div>
              </div>
            </div>
          )}

          {downloadMut.isError && (
            <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <XCircle className="h-4 w-4" />
              {(downloadMut.error as Error)?.message || 'Download failed'}
            </div>
          )}
        </form>
      </CardContent>
      {downloadMut.isSuccess && (
        <CardFooter className="border-t pt-4">
          <Button variant="outline" size="sm" onClick={onClose}>Done</Button>
        </CardFooter>
      )}
    </Card>
  )
}
