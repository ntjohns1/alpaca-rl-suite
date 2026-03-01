import { FastifyRequest, FastifyReply, HookHandlerDoneFunction } from 'fastify';
import { v4 as uuidv4 } from 'uuid';

export function correlationId(
  req: FastifyRequest,
  _reply: FastifyReply,
  done: HookHandlerDoneFunction,
) {
  const traceId = (req.headers['x-trace-id'] as string) ?? uuidv4();
  (req as any).traceId = traceId;
  done();
}
