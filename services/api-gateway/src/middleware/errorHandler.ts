import { FastifyError, FastifyReply, FastifyRequest } from 'fastify';

export function errorHandler(
  error: FastifyError,
  req: FastifyRequest,
  reply: FastifyReply,
) {
  const traceId = (req as any).traceId;
  const statusCode = error.statusCode ?? 500;

  req.log.error({ err: error, traceId }, 'Request error');

  reply.status(statusCode).send({
    error: error.message ?? 'Internal Server Error',
    code: error.code,
    traceId,
  });
}
