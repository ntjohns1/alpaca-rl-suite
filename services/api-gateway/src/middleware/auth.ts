import { FastifyRequest, FastifyReply } from 'fastify';

// Paths that do not require a JWT — the auth service itself plus health.
// /metrics is intentionally absent: it is served on a separate internal port
// and never reaches this middleware.
const PUBLIC_PREFIXES = ['/auth', '/health'];

export function isPublicPath(url: string): boolean {
  return PUBLIC_PREFIXES.some(
    (prefix) =>
      url === prefix ||
      url.startsWith(prefix + '/') ||
      url.startsWith(prefix + '?'),
  );
}

export async function authenticate(req: FastifyRequest, reply: FastifyReply): Promise<void> {
  if (isPublicPath(req.url)) return;
  try {
    await req.jwtVerify();
  } catch (err) {
    // Log the specific error so expired/invalid-signature/malformed tokens are
    // distinguishable in production without leaking details to the caller.
    req.log.warn({ err, url: req.url }, 'JWT verification failed');
    reply.status(401).send({ error: 'Unauthorized' });
  }
}
