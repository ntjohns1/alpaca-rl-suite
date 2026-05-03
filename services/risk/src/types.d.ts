import 'fastify';

declare module 'fastify' {
  interface FastifyRequest {
    authSub?: string;
  }
}
