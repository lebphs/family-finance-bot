import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { api } from './api';
import { getTelegram } from './telegram';
import { localPreviewEnabled } from './preview-mode';
import './styles.css';

async function start() {
  let client = api;
  if (import.meta.env.DEV && localPreviewEnabled(import.meta.env.DEV,
      import.meta.env.VITE_LOCAL_PREVIEW, window.location.hostname, getTelegram()?.initData ?? '')) {
    const { createPreviewClient } = await import('./preview');
    client = createPreviewClient();
  }
  createRoot(document.getElementById('root')!).render(<StrictMode><App client={client} /></StrictMode>);
}
void start();
