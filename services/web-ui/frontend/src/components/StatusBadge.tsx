import { Badge } from '@/components/ui/badge'

const STATUS_COLORS: Record<string, string> = {
  ok:               'bg-green-100 text-green-800 border-green-200',
  healthy:          'bg-green-100 text-green-800 border-green-200',
  completed:        'bg-green-100 text-green-800 border-green-200',
  approved:         'bg-green-100 text-green-800 border-green-200',
  running:          'bg-blue-100 text-blue-800 border-blue-200',
  training_on_kaggle: 'bg-blue-100 text-blue-800 border-blue-200',
  preparing:        'bg-blue-100 text-blue-800 border-blue-200',
  pending:          'bg-yellow-100 text-yellow-800 border-yellow-200',
  pending_approval: 'bg-amber-100 text-amber-800 border-amber-200',
  degraded:         'bg-yellow-100 text-yellow-800 border-yellow-200',
  failed:           'bg-red-100 text-red-800 border-red-200',
  error:            'bg-red-100 text-red-800 border-red-200',
  rejected:         'bg-red-100 text-red-800 border-red-200',
  cancelled:        'bg-gray-100 text-gray-800 border-gray-200',
  unreachable:      'bg-gray-100 text-gray-800 border-gray-200',
  timeout:          'bg-gray-100 text-gray-800 border-gray-200',
}

export function StatusBadge({ status }: { status: string }) {
  const colors = STATUS_COLORS[status] || 'bg-gray-100 text-gray-600 border-gray-200'
  return (
    <Badge variant="outline" className={colors}>
      {status.replace(/_/g, ' ')}
    </Badge>
  )
}
