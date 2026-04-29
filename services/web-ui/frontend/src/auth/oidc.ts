import { oidcSpa } from "oidc-spa/react-spa";
import { z } from "zod";

interface AuthConfig {
  url: string;
  realm: string;
  clientId: string;
}

async function loadAuthConfig(): Promise<AuthConfig> {
  try {
    const resp = await fetch("/api/auth/config", { credentials: "same-origin" });
    if (resp.ok) {
      const cfg = (await resp.json()) as AuthConfig;
      if (cfg.url && cfg.realm && cfg.clientId) return cfg;
    }
  } catch {
    // Fall through to env-var fallback for local dev when backend isn't up.
  }

  const url = import.meta.env.VITE_KEYCLOAK_URL;
  const realm = import.meta.env.VITE_KEYCLOAK_REALM;
  const clientId = import.meta.env.VITE_KEYCLOAK_CLIENT_ID;
  if (!url || !realm || !clientId) {
    throw new Error(
      "Keycloak config unavailable: /api/auth/config failed and VITE_KEYCLOAK_* env vars are not set"
    );
  }
  return { url, realm, clientId };
}

export const {
  bootstrapOidc,
  useOidc,
  getOidc,
  OidcInitializationGate,
} = oidcSpa
  .withExpectedDecodedIdTokenShape({
    decodedIdTokenSchema: z.object({
      sub: z.string(),
      name: z.string().optional(),
      email: z.string().email().optional(),
      preferred_username: z.string().optional(),
      given_name: z.string().optional(),
      family_name: z.string().optional(),
      realm_access: z.object({ roles: z.array(z.string()) }).optional(),
    }),
  })
  .createUtils();

let bootstrapPromise: Promise<void> | null = null;

export function bootstrapAuth(): Promise<void> {
  if (bootstrapPromise) return bootstrapPromise;
  bootstrapPromise = (async () => {
    const cfg = await loadAuthConfig();
    bootstrapOidc({
      implementation: "real",
      issuerUri: `${cfg.url.replace(/\/$/, "")}/realms/${cfg.realm}`,
      clientId: cfg.clientId,
      debugLogs: import.meta.env.DEV,
    });
  })();
  return bootstrapPromise;
}

/**
 * Fetch wrapper that attaches the access token as Authorization header.
 */
export const fetchWithAuth: typeof fetch = async (input, init) => {
  const oidc = await getOidc();

  if (oidc.isUserLoggedIn) {
    const accessToken = await oidc.getAccessToken();
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${accessToken}`);
    (init ??= {}).headers = headers;
  }

  return fetch(input, init);
};
