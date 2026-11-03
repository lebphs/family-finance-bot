import { FormEvent, useEffect, useRef, useState } from 'react';
import { ApiClient, ApiError, CurrentUser, Trip, TripInput, TripReport } from '../api';

const money = (value: string) => `${Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} BYN`;

export function Trips({ client, user, onDenied, onChanged, onExpense }: {
  client: ApiClient; user: CurrentUser; onDenied: () => void; onChanged: () => void; onExpense: (trip: Trip) => void;
}) {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [currencies, setCurrencies] = useState<string[]>(['BYN', 'EUR', 'USD']);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selected, setSelected] = useState('');
  const [report, setReport] = useState<TripReport | null>(null);
  const [filter, setFilter] = useState('');
  const [form, setForm] = useState<TripInput>({ name: '', date_from: '', date_to: '', currency: 'EUR' });
  const [editing, setEditing] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const lock = useRef(false);
  const deny = useRef(onDenied); deny.current = onDenied;

  useEffect(() => {
    const controller = new AbortController();
    setReady(false); setError('');
    Promise.all([client.trips(controller.signal), client.travelContext(controller.signal)]).then(([items, context]) => {
      if (!controller.signal.aborted) { setTrips(items); setActiveId(context.trip?.trip_id ?? null); setCurrencies(context.currencies); setReady(true); }
    }).catch(err => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setError('Не удалось загрузить поездки.');
    });
    return () => controller.abort();
  }, [client, revision]);

  useEffect(() => {
    const controller = new AbortController();
    setReport(null); setFilter('');
    if (selected) client.tripReport(selected, controller.signal).then(value => {
      if (!controller.signal.aborted) setReport(value);
    }).catch(err => {
      if (controller.signal.aborted) return;
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setError('Не удалось загрузить отчёт поездки.');
    });
    return () => controller.abort();
  }, [client, selected, revision]);

  async function act(action: () => Promise<unknown>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await action(); onChanged(); setRevision(n => n + 1); }
    catch (err) {
      if (err instanceof ApiError && err.accessDenied) deny.current();
      else setError(err instanceof ApiError ? err.message : 'Не удалось сохранить. Обновите список перед повторной попыткой.');
    } finally { lock.current = false; setBusy(false); }
  }
  function save(event: FormEvent) {
    event.preventDefault();
    void act(async () => {
      const trip = editing ? await client.updateTrip(editing, form) : await client.createTrip(form);
      setSelected(trip.trip_id); setFormOpen(false);
    });
  }
  const canEdit = report && (user.role === 'admin' || report.trip.created_by === user.telegram_user_id);
  return <div className="trips">
    <section className="home-card">
      <h2>Поездки</h2>
      <p>Режим поездки меняет ваши категории и валюту. У других участников остаётся их собственный режим.</p>
      {activeId && <button className="secondary-button" disabled={busy} onClick={() => void act(() => client.setTravelMode(null))}>Выключить режим поездки</button>}
      <button className="primary-button" disabled={busy || !ready} onClick={() => {
        setEditing(null); setForm({ name: '', date_from: '', date_to: '', currency: 'EUR' }); setFormOpen(true);
      }}>Создать поездку</button>
      {!ready && !error && <p role="status">Загружаем поездки…</p>}
      {ready && !trips.length && <p>Поездок пока нет. Можно создать будущую поездку и записывать билеты заранее.</p>}
      <ul className="recent-list">{trips.map(trip => <li key={trip.trip_id}>
        <button className="transaction-button" disabled={busy} aria-pressed={selected === trip.trip_id} onClick={() => { setSelected(trip.trip_id); setFormOpen(false); setError(''); }}>
          <strong>{trip.name}{activeId === trip.trip_id ? ' · Ваш активный режим' : ''}</strong>
          <span>{trip.date_from} — {trip.date_to} · {trip.currency} · {trip.completed ? 'Завершена' : 'Открыта'}</span>
        </button>
      </li>)}</ul>
    </section>
    {formOpen && <section className="home-card"><h2>{editing ? 'Изменить поездку' : 'Новая поездка'}</h2>
      <form onSubmit={save}><fieldset disabled={busy}>
        <label>Название поездки<input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
        <label>Начало поездки<input required type="date" value={form.date_from} onChange={e => setForm({ ...form, date_from: e.target.value })} /></label>
        <label>Окончание поездки<input required type="date" min={form.date_from} value={form.date_to} onChange={e => setForm({ ...form, date_to: e.target.value })} /></label>
        <label>Валюта поездки<select value={form.currency} onChange={e => setForm({ ...form, currency: e.target.value })}>{currencies.map(c => <option key={c}>{c}</option>)}</select></label>
      </fieldset><button className="primary-button" disabled={busy}>Сохранить поездку</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setFormOpen(false)}>Отменить</button></form>
    </section>}
    {selected && !report && !error && <p role="status">Загружаем отчёт…</p>}
    {report && <section className="home-card" aria-label="Отчёт поездки">
      <h2>{report.trip.name}</h2><p>{report.trip.date_from} — {report.trip.date_to}</p>
      <p>Всего: <strong>{money(report.total)}</strong> · {report.count} операций</p>
      <p>Включены все оплаты поездки, в том числе билеты и проживание, купленные заранее.</p>
      {!report.trip.completed && <button className="secondary-button" disabled={busy} onClick={() => void act(() => client.setTravelMode(activeId === selected ? null : selected))}>{activeId === selected ? 'Выключить режим этой поездки' : 'Включить режим этой поездки'}</button>}
      <button className="primary-button" disabled={busy} onClick={() => onExpense(report.trip)}>Добавить расход в эту поездку</button>
      {canEdit && <button className="secondary-button" disabled={busy} onClick={() => {
        setEditing(report.trip.trip_id); const { name, date_from, date_to, currency } = report.trip;
        setForm({ name, date_from, date_to, currency }); setFormOpen(true);
      }}>Изменить поездку</button>}
      {canEdit && !report.trip.completed && <button className="secondary-button" disabled={busy} onClick={() => void act(() => client.completeTrip(selected))}>Завершить поездку</button>}
      <h3>По категориям</h3>
      <ul className="recent-list">{report.categories.map(c => <li key={c.category}><button className="transaction-button" aria-pressed={filter === c.category} onClick={() => setFilter(filter === c.category ? '' : c.category)}>{c.category} · {money(c.amount)}</button></li>)}</ul>
      <h3>По участникам</h3><ul>{report.participants.map(p => <li key={p.author_id ?? 'unknown'}>{p.author_name}: {money(p.amount)}</li>)}</ul>
      <h3>{filter || 'Все расходы'}</h3>
      {filter && <button className="secondary-button" onClick={() => setFilter('')}>Показать все расходы поездки</button>}
      <ul className="recent-list">{report.transactions.filter(t => !filter || t.category === filter).map(t => <li key={t.transaction_id}>
        <strong>{t.category} · {money(t.amount)}</strong><p>{t.description || 'Без описания'}</p>
        <span>{t.date} · {t.author_name} · {t.original_amount ?? t.amount} {t.currency ?? 'BYN'}</span>
      </li>)}</ul>
    </section>}
    {error && <p role="alert">{error}</p>}
    <button className="secondary-button" disabled={busy} onClick={() => setRevision(n => n + 1)}>Обновить поездки</button>
  </div>;
}
