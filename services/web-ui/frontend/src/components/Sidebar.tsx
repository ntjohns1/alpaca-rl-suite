import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  GraduationCap,
  ShieldCheck,
  Brain,
  Database,
  Activity,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  badge?: number
}

export function Sidebar({ pendingApprovals }: { pendingApprovals?: number }) {
  const items: NavItem[] = [
    { to: '/',           label: 'Dashboard',  icon: LayoutDashboard },
    { to: '/training',   label: 'Training',   icon: GraduationCap },
    { to: '/approvals',  label: 'Approvals',  icon: ShieldCheck, badge: pendingApprovals },
    { to: '/policies',   label: 'Policies',   icon: Brain },
    { to: '/datasets',   label: 'Datasets',   icon: Database },
    { to: '/monitoring', label: 'Monitoring', icon: Activity },
  ]

  return (
    <aside className="flex h-screen w-60 flex-col border-r bg-card">
      <div className="flex h-14 items-center border-b px-4">
        <span className="text-lg font-bold text-primary">🦙 Alpaca RL</span>
      </div>
      <nav className="flex-1 space-y-1 p-2">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
              )
            }
          >
            <item.icon className="h-4 w-4" />
            {item.label}
            {item.badge != null && item.badge > 0 && (
              <span className="ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500 px-1.5 text-[10px] font-bold text-white">
                {item.badge}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="border-t p-3 text-xs text-muted-foreground">
        Alpaca RL Suite v1.0
      </div>
    </aside>
  )
}
