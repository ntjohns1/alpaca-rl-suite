import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

const sdk = new NodeSDK({
  serviceName: 'market-ingest',
  traceExporter: new OTLPTraceExporter({
    url: `${process.env['OTEL_EXPORTER_OTLP_ENDPOINT'] ?? 'http://localhost:4318'}/v1/traces`,
  }),
});

sdk.start();

// Callers (index.ts) sequence this after other shutdown steps before process.exit.
export async function shutdown(): Promise<void> {
  await sdk.shutdown();
}
