import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { OidcInitializationGate, bootstrapAuth } from './auth/oidc'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
      refetchIntervalInBackground: false,
    },
  },
})

const loadingScreen = (
  <div className="flex h-screen items-center justify-center bg-background">
    <div className="text-center">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent mx-auto" />
      <p className="mt-4 text-muted-foreground">Checking authentication...</p>
    </div>
  </div>
)

const root = ReactDOM.createRoot(document.getElementById('root')!)
root.render(loadingScreen)

bootstrapAuth().then(() => {
  root.render(
    <React.StrictMode>
      <OidcInitializationGate fallback={loadingScreen}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </OidcInitializationGate>
    </React.StrictMode>,
  )
}).catch((err) => {
  root.render(
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="max-w-md text-center">
        <p className="text-lg font-medium text-destructive">Authentication unavailable</p>
        <p className="mt-2 text-sm text-muted-foreground">{String(err.message ?? err)}</p>
      </div>
    </div>
  )
})
