import { useOidc } from '@/auth/oidc'
import { LogIn } from 'lucide-react'

export function LoginPage() {
  const oidc = useOidc()

  return (
    <div className="flex h-screen items-center justify-center bg-gradient-to-br from-background to-muted">
      <div className="w-full max-w-md space-y-8 rounded-lg border bg-card p-8 shadow-lg">
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
            <span className="text-4xl">🦙</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight">Alpaca RL Suite</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Reinforcement Learning Trading Platform
          </p>
        </div>

        <div className="space-y-4">
          <div className="rounded-md border border-muted bg-muted/50 p-4">
            <p className="text-sm text-muted-foreground">
              Sign in with your Keycloak account to access the dashboard, training jobs, 
              policy management, and more.
            </p>
          </div>

          <button
            onClick={() => oidc.login?.({ redirectUrl: window.location.href })}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-3 text-sm font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
          >
            <LogIn className="h-4 w-4" />
            Sign in with Keycloak
          </button>
        </div>

        <div className="border-t pt-4">
          <p className="text-center text-xs text-muted-foreground">
            Secured by Keycloak • OAuth 2.0 / OIDC
          </p>
        </div>
      </div>
    </div>
  )
}
