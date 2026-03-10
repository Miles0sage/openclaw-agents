const gatewayUrl = import.meta.env.VITE_GATEWAY_URL ?? 'https://<your-domain>';
const useMocks = import.meta.env.VITE_USE_MOCKS === 'true';

export const GATEWAY_BASE = gatewayUrl.replace(/\/$/, '');
export const USE_MOCKS = useMocks;
export const ANALYTICS_BASE = `${GATEWAY_BASE}/api/analytics`;
