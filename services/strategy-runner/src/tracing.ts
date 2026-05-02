import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

// Single global so index.ts can fold OTel shutdown into its own SIGTERM
// handler. We deliberately do NOT register a SIGTERM listener here — having
// two competing handlers (one of which calls process.exit) causes the
// in-flight tick drain in index.ts to be preempted.
export const otelSdk = new NodeSDK({
  serviceName: 'strategy-runner',
  traceExporter: new OTLPTraceExporter({
    url: `${process.env['OTEL_EXPORTER_OTLP_ENDPOINT'] ?? 'http://localhost:4318'}/v1/traces`,
  }),
});

otelSdk.start();
