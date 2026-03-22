import { oidcSpa } from "oidc-spa/react-spa";
import { z } from "zod";

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
    decodedIdToken_mock: {
      sub: "mock-user",
      name: "Mock User",
      email: "mock@example.com",
      preferred_username: "mockuser",
    },
  })
  .createUtils();

// Bootstrap immediately — oidc-spa handles all redirect/token logic internally.
// issuerUri is the Keycloak realm URL (NOT the base Keycloak URL).
bootstrapOidc({
  implementation: "real",
  issuerUri: "https://auth.nelsonjohns.com/realms/admin",
  clientId: "alpaca-rl-web-ui",
  debugLogs: true,
});

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
