import { Routes, Route } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Sidebar } from '@/components/Sidebar'
import { Dashboard } from '@/pages/Dashboard'
import { Training } from '@/pages/Training'
import { Approvals } from '@/pages/Approvals'
import { Policies } from '@/pages/Policies'
import { Datasets } from '@/pages/Datasets'
import { Monitoring } from '@/pages/Monitoring'
import { fetchOverview } from '@/api/client'

export default function App() {
  const { data: overview } = useQuery({
    queryKey: ['overview'],
    queryFn: fetchOverview,
  })

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar pendingApprovals={overview?.pendingApprovals} />
      <main className="flex-1 overflow-y-auto">
        <div className="container max-w-7xl py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/training" element={<Training />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/policies" element={<Policies />} />
            <Route path="/datasets" element={<Datasets />} />
            <Route path="/monitoring" element={<Monitoring />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}
