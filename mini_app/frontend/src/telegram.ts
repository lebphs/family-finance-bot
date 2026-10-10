export type Insets = { top: number; bottom: number; left: number; right: number };
export type TelegramEvent = 'themeChanged' | 'viewportChanged' | 'safeAreaChanged' | 'contentSafeAreaChanged';
export interface TelegramWebApp {
  initData: string;
  colorScheme: 'light' | 'dark';
  themeParams: Record<string, string | undefined>;
  safeAreaInset?: Insets;
  contentSafeAreaInset?: Insets;
  viewportStableHeight?: number;
  ready(): void;
  expand(): void;
  onEvent(event: TelegramEvent, callback: () => void): void;
  offEvent(event: TelegramEvent, callback: () => void): void;
}

declare global {
  interface Window { Telegram?: { WebApp?: TelegramWebApp } }
}

export function getTelegram(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

// The SDK is also present in a regular browser; empty initData means no Telegram session.
export function initializeTelegram(): () => void {
  const app = getTelegram();
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const root = document.documentElement;
  const colors = {
    bg_color: '--app-bg', text_color: '--app-text', hint_color: '--app-hint',
    secondary_bg_color: '--app-surface', button_color: '--app-accent',
    button_text_color: '--app-accent-text',
  };
  const sync = () => {
    const inTelegram = Boolean(app?.initData);
    const theme = inTelegram ? app!.colorScheme : media.matches ? 'dark' : 'light';
    root.dataset.theme = theme;
    for (const [name, variable] of Object.entries(colors)) {
      const value = inTelegram ? app?.themeParams[name] : undefined;
      if (value) root.style.setProperty(variable, value);
      else root.style.removeProperty(variable);
    }
    for (const side of ['top', 'bottom', 'left', 'right'] as const) {
      const safe = inTelegram ? app?.safeAreaInset?.[side] ?? 0 : 0;
      const content = inTelegram ? app?.contentSafeAreaInset?.[side] ?? 0 : 0;
      root.style.setProperty(`--tg-safe-${side}`, `${Math.max(0, safe)}px`);
      root.style.setProperty(`--tg-content-safe-${side}`, `${Math.max(0, content)}px`);
    }
    if (inTelegram && app?.viewportStableHeight) {
      root.style.setProperty('--app-height', `${app.viewportStableHeight}px`);
    } else root.style.removeProperty('--app-height');
  };
  const events: TelegramEvent[] = ['themeChanged', 'viewportChanged', 'safeAreaChanged', 'contentSafeAreaChanged'];
  sync();
  media.addEventListener('change', sync);
  if (app?.initData) {
    events.forEach((event) => app.onEvent(event, sync));
    app.ready();
    app.expand();
  }
  return () => {
    media.removeEventListener('change', sync);
    if (app?.initData) events.forEach((event) => app.offEvent(event, sync));
  };
}
