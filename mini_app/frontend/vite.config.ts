import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';

export default defineConfig(({ mode }) => {
  // Only explicitly public frontend settings; never load the repository .env.
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const tunnelHost = env.VITE_TUNNEL_HOST;
  if (tunnelHost && !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i.test(tunnelHost)) {
    throw new Error('VITE_TUNNEL_HOST должен содержать только имя хоста');
  }
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      allowedHosts: tunnelHost ? [tunnelHost] : [],
      proxy: {
        '/api': {
          target: mode === 'e2e' ? 'http://127.0.0.1:18000' : 'http://127.0.0.1:8000',
          configure(proxy) {
            proxy.on('proxyReq', (proxyReq, req) => {
              const host = req.headers.host?.split(':')[0];
              if (host !== 'localhost' && host !== '127.0.0.1') {
                proxyReq.removeHeader('X-Dev-Telegram-User-Id');
              }
            });
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      restoreMocks: true,
      clearMocks: true,
    },
  };
});
