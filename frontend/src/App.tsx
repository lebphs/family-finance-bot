import { useEffect, useState } from 'react';
import { api, ApiClient, ApiError, CurrentUser } from './api';
import { StatusScreen } from './components/StatusScreen';
import { initializeTelegram } from './telegram';
import { Home } from './components/Home';
import { FinanceIcon } from './components/FinanceIcon';
import { Statistics } from './components/Statistics';
import { Settings } from './components/Settings';
import { Transactions } from './components/Transactions';

const pages = [
  { id: 'home', label: 'Главная', icon: 'home', title: 'Семейные расходы', description: 'Здесь будут быстрое добавление расхода и сводка семейного бюджета.' },
  { id: 'transactions', label: 'Транзакции', icon: 'list', title: 'Транзакции', description: 'Здесь появятся история расходов, поиск и фильтры.' },
  { id: 'statistics', label: 'Статистика', icon: 'chart', title: 'Статистика', description: 'Здесь можно будет сравнивать расходы по месяцам, категориям и участникам.' },
  { id: 'settings', label: 'Настройки', icon: 'settings', title: 'Настройки', description: 'Здесь появятся персональные настройки напоминаний.' },
] as const;
type PageId = typeof pages[number]['id'];
type Session = { kind: 'loading' } | { kind: 'ready'; user: CurrentUser } | { kind: 'denied' } | { kind: 'error'; message: string };

export function App({ client = api }: { client?: ApiClient }) {
  const [session, setSession] = useState<Session>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [homeRevision, setHomeRevision] = useState(0);
  const [pageId, setPageId] = useState<PageId>('home');
  useEffect(initializeTelegram, []);
  useEffect(() => {
    const controller = new AbortController();
    setSession({ kind: 'loading' });
    client.me(controller.signal).then((user) => {
      if (!controller.signal.aborted) setSession({ kind: 'ready', user });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.accessDenied) setSession({ kind: 'denied' });
      else setSession({ kind: 'error', message: error instanceof ApiError ? error.message : 'Не удалось загрузить приложение.' });
    });
    return () => controller.abort();
  }, [client, attempt]);

  if (session.kind !== 'ready') {
    return <main className="access-screen">
      <p className="brand">Семейные расходы</p>
      {session.kind === 'loading' && <StatusScreen kind="loading" title="Загружаем приложение" description="Проверяем доступ к семейной книге." />}
      {session.kind === 'denied' && <StatusScreen kind="denied" title="Нет доступа" description="Откройте приложение через Telegram. Доступ предоставляется только участникам семьи; обратитесь к администратору." />}
      {session.kind === 'error' && <StatusScreen kind="error" title="Не удалось загрузить приложение" description={session.message} onRetry={() => setAttempt((value) => value + 1)} />}
    </main>;
  }
  return <div className="app-shell">
    <header className="page-header">
      <h1>Семейные расходы</h1>
    </header>
    <main id="page-content" className="page-content">
      <div hidden={pageId !== 'home'}><Home refresh={homeRevision} client={client} onDenied={() => setSession({ kind: 'denied' })} onTransactions={() => setPageId('transactions')} /></div>
      {pageId === 'transactions' && <Transactions client={client} user={session.user} onDenied={() => setSession({ kind: 'denied' })} onChanged={() => setHomeRevision((n) => n + 1)} />}
      {pageId === 'statistics' && <Statistics client={client} onDenied={() => setSession({ kind: 'denied' })} />}
      {pageId === 'settings' && <section className="profile-card" aria-label="Ваш профиль">
        <span className="avatar" aria-hidden="true">{session.user.display_name.slice(0, 1)}</span>
        <div><strong>{session.user.display_name}</strong><p>{session.user.role === 'admin' ? 'Администратор' : 'Участник семьи'}</p></div>
      </section>}
      {pageId === 'settings' && <Settings client={client} user={session.user} onDenied={() => setSession({ kind: 'denied' })} />}
    </main>
    <nav className="bottom-nav" aria-label="Основная навигация">
      {pages.map((item) => <button key={item.id} type="button" aria-current={pageId === item.id ? 'page' : undefined} aria-controls="page-content" onClick={() => setPageId(item.id)}>
        <FinanceIcon className="nav-icon" name={item.icon} /><span>{item.label}</span>
      </button>)}
    </nav>
  </div>;
}
