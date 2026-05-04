import type { FastifyReply, FastifyRequest } from 'fastify';
import jwt from 'jsonwebtoken';

/**
 * Returns a Fastify preHandler factory that validates a Bearer JWT.
 *
 * The token must be signed with HS256, have `audience` in its `aud` claim,
 * and (when `scope` is supplied) contain that scope in its `scope` claim.
 *
 * After successful verification, `req.authSub` is populated with the token's
 * `sub` claim for use in audit logs. Services that need typed access should
 * add `authSub?: string` to Fastify's `FastifyRequest` interface via a local
 * `types.d.ts` augmentation.
 *
 * NOTE: The auth service currently mints a universal token whose `scope`
 * covers every service. The scope checks here are therefore advisory rather
 * than truly restrictive. Proper per-caller scoped tokens are tracked as a
 * follow-up to ALPCA-8 and must be addressed before any service is exposed
 * beyond the internal cluster.
 */
export function createRequireAuth(jwtSecret: string, audience: string) {
  return (scope?: string) =>
    async (req: FastifyRequest, reply: FastifyReply) => {
      const auth = req.headers.authorization;
      if (!auth?.startsWith('Bearer ')) {
        req.log.warn({ ip: req.ip, route: req.url }, 'auth: missing bearer token');
        return reply.status(401).send({ error: 'missing bearer token' });
      }

      let payload: jwt.JwtPayload;
      try {
        const decoded = jwt.verify(auth.slice(7), jwtSecret, {
          algorithms: ['HS256'],
          audience,
        });
        // jwt.verify with a string secret returns JwtPayload or string.
        // A bare string payload would have no `sub` or `scope`, treat as invalid.
        if (typeof decoded === 'string') throw new Error('unexpected string payload');
        payload = decoded;
      } catch (err: unknown) {
        const reason = err instanceof Error ? err.name : 'unknown';
        req.log.warn({ ip: req.ip, route: req.url, reason }, 'auth: token verification failed');
        return reply.status(401).send({ error: 'invalid token' });
      }

      if (scope) {
        const claim = payload.scope;
        const scopes = typeof claim === 'string' ? claim.split(/\s+/).filter(Boolean) : [];
        if (!scopes.includes(scope)) {
          req.log.warn(
            { ip: req.ip, route: req.url, sub: payload.sub, required: scope },
            'auth: missing required scope',
          );
          return reply.status(403).send({ error: 'insufficient scope', required: scope });
        }
      }

      // Populated for audit logging; services declare the type via types.d.ts augmentation.
      (req as any).authSub = payload.sub;
    };
}
