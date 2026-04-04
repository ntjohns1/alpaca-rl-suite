import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  GraduationCap,
  ShieldCheck,
  Brain,
  Database,
  Activity,
  LogOut,
  User,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useOidc } from '@/auth/oidc'

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
      <UserProfile />
    </aside>
  )
}

function UserProfile() {
  const oidc = useOidc()

  // Sidebar only renders when authenticated, so this should always be true
  if (!oidc.isUserLoggedIn) return null

  const { decodedIdToken } = oidc

  return (
    <div className="border-t">
      <div className="flex items-center gap-3 p-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10">
          <User className="h-4 w-4 text-primary" />
        </div>
        <div className="flex-1 overflow-hidden">
          <p className="truncate text-sm font-medium">
            {decodedIdToken.name || decodedIdToken.preferred_username || 'User'}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {decodedIdToken.email || ''}
          </p>
        </div>
      </div>
      <div className="px-2 pb-2">
        <button
          onClick={() => oidc.logout({ redirectTo: "current page" })}
          className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <LogOut className="h-4 w-4" />
          Logout
        </button>
      </div>
    </div>
  )
}
