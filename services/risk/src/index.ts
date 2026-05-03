import './tracing';
import { loadConfig } from '@alpaca-rl/config';
import { createApp } from './app';

const config = loadConfig();
const app = createApp(config);

app.listen({ port: config.RISK_PORT, host: '0.0.0.0' }, (err) => {
  if (err) { app.log.error(err); process.exit(1); }
});
