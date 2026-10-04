import { describe, expect, it, vi } from 'vitest';
import { initializeTelegram, TelegramEvent, TelegramWebApp } from './telegram';

describe('Telegram SDK', () => {
  it('работает без SDK и следует системной теме браузера', () => {
    const media = { matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() };
    vi.stubGlobal('matchMedia', vi.fn(() => media));
    const dispose = initializeTelegram();
    expect(document.documentElement.dataset.theme).toBe('dark');
    media.matches = false;
    media.addEventListener.mock.calls[0][1]();
    expect(document.documentElement.dataset.theme).toBe('light');
    dispose();
    expect(media.removeEventListener).toHaveBeenCalled();
  });

  it('применяет тему, viewport и safe areas; обновляет события и снимает подписки', () => {
    const callbacks = new Map<TelegramEvent, () => void>();
    const app: TelegramWebApp = {
      initData: 'signed', colorScheme: 'dark', themeParams: { bg_color: '#121212' },
      safeAreaInset: { top: 30, bottom: 20, left: 0, right: 0 },
      contentSafeAreaInset: { top: 10, bottom: 5, left: 0, right: 0 }, viewportStableHeight: 700,
      ready: vi.fn(), expand: vi.fn(),
      onEvent: vi.fn((event, callback) => { callbacks.set(event, callback); }), offEvent: vi.fn(),
    };
    window.Telegram = { WebApp: app };
    const dispose = initializeTelegram();
    const root = document.documentElement;
    expect(app.ready).toHaveBeenCalledOnce();
    expect(app.expand).toHaveBeenCalledOnce();
    expect(root.dataset.theme).toBe('dark');
    expect(root.style.getPropertyValue('--app-bg')).toBe('#121212');
    expect(root.style.getPropertyValue('--tg-safe-top')).toBe('30px');
    expect(root.style.getPropertyValue('--tg-content-safe-bottom')).toBe('5px');
    expect(root.style.getPropertyValue('--app-height')).toBe('700px');
    app.colorScheme = 'light'; app.themeParams = {};
    callbacks.get('themeChanged')!();
    expect(root.dataset.theme).toBe('light');
    expect(root.style.getPropertyValue('--app-bg')).toBe('');
    app.safeAreaInset!.bottom = 44;
    callbacks.get('safeAreaChanged')!();
    expect(root.style.getPropertyValue('--tg-safe-bottom')).toBe('44px');
    dispose();
    expect(app.offEvent).toHaveBeenCalledTimes(4);
    for (const [event, callback] of callbacks) expect(app.offEvent).toHaveBeenCalledWith(event, callback);
  });

  it('не принимает браузерный SDK с пустым initData за Telegram', () => {
    const ready = vi.fn();
    window.Telegram = { WebApp: { initData: '', colorScheme: 'dark', themeParams: {}, ready } as unknown as TelegramWebApp };
    const dispose = initializeTelegram();
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(ready).not.toHaveBeenCalled();
    dispose();
  });
});
