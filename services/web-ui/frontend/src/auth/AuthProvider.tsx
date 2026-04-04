// AuthProvider is no longer needed — oidc-spa handles everything via
// OidcInitializationGate in main.tsx and the useOidc() hook.
//
// This file re-exports the oidc-spa hooks so existing components
// can import from '@/auth/AuthProvider' without changes during migration.

export { useOidc, OidcInitializationGate } from './oidc'

// Convenience wrapper that maps oidc-spa's API to the shape
// the rest of the app already expects.
import { useOidc } from './oidc'

export function useAuth() {
  const oidc = useOidc()

  if (oidc.isUserLoggedIn) {
    return {
      isAuthenticated: true as const,
      isLoading: false,
      user: {
        sub: oidc.decodedIdToken.sub,
        email: oidc.decodedIdToken.email,
        name: oidc.decodedIdToken.name,
        preferredUsername: oidc.decodedIdToken.preferred_username,
        givenName: oidc.decodedIdToken.given_name,
        familyName: oidc.decodedIdToken.family_name,
      },
      logout: () => oidc.logout({ redirectTo: "current page" }),
    }
  }

  return {
    isAuthenticated: false as const,
    isLoading: false,
    user: null,
    logout: () => {},
  }
}
