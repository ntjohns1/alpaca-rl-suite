import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

const sdk = new NodeSDK({
  serviceName: 'risk',
  traceExporter: new OTLPTraceExporter({
    url: `${process.env['OTEL_EXPORTER_OTLP_ENDPOINT'] ?? 'http://localhost:4318'}/v1/traces`,
  }),
});

sdk.start();

process.on('SIGTERM', () => {
  sdk.shutdown().finally(() => process.exit(0));
});
