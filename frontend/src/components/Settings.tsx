import { FormEvent, useEffect, useRef, useState } from 'react';
import { ApiClient, ApiError, CurrentUser, ManagedUser, ReminderResponse } from '../api';

const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
export function Settings({ client, user, onDenied }: { client: ApiClient; user: CurrentUser; onDenied: () => void }) {
  const [settings, setSettings] = useState<ReminderResponse>();
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const sending = useRef(false);
  function failed(e: unknown) {
    if (e instanceof ApiError && e.accessDenied) onDenied();
    else setError(e instanceof ApiError ? e.message : 'Не удалось сохранить настройки. Попробуйте ещё раз.');
  }
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    client.reminders(controller.signal).then(s => { if (!controller.signal.aborted) setSettings(s); })
      .catch(e => { if (!controller.signal.aborted) failed(e); });
    return () => controller.abort();
  }, [client, attempt]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings || sending.current) return;
    if (settings.reminder_days.length === 0) { setError('Выберите хотя бы один день недели.'); return; }
    sending.current = true; setBusy(true); setSaved(false); setError('');
    try {
      const { chat_connected: _, ...input } = settings;
      setSettings(await client.saveReminders(input)); setSaved(true);
    } catch (e) { failed(e); }
    finally { sending.current = false; setBusy(false); }
  }
  return <div className="settings">
    <section className="home-card">
      <h2>Персональные напоминания</h2>
      {!settings && !error && <p role="status">Загружаем настройки…</p>}
      {!settings && error && <><p role="alert">{error}</p><button className="secondary-button" onClick={() => setAttempt(n => n + 1)}>Повторить</button></>}
      {settings && <form onSubmit={save}>
        <fieldset disabled={busy}>
          <label className="check-label"><input type="checkbox" checked={settings.reminder_enabled} onChange={e => { setSaved(false); setSettings({ ...settings, reminder_enabled: e.target.checked }); }} />Включить напоминания</label>
          <label>Время<input type="time" required value={settings.reminder_time} onChange={e => { setSaved(false); setSettings({ ...settings, reminder_time: e.target.value }); }} /></label>
          <label>Часовой пояс<input required value={settings.timezone} placeholder="Europe/Minsk" onChange={e => { setSaved(false); setSettings({ ...settings, timezone: e.target.value }); }} /></label>
          <fieldset><legend>Дни недели</legend><div className="weekdays">{weekdays.map((name, day) => <label className="check-label" key={day}><input type="checkbox" checked={settings.reminder_days.includes(day)} onChange={e => {
            setSaved(false); setSettings({ ...settings, reminder_days: e.target.checked ? [...settings.reminder_days, day].sort() : settings.reminder_days.filter(d => d !== day) });
          }} />{name}</label>)}</div></fieldset>
        </fieldset>
        {!settings.chat_connected && <p>Для получения напоминаний откройте личный чат с ботом и отправьте /start.</p>}
        {error && <p role="alert" className="form-error">{error}</p>}
        {saved && <p role="status">Настройки сохранены</p>}
        <button className="primary-button" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить настройки'}</button>
      </form>}
    </section>
    {user.role === 'admin' && <Members client={client} onDenied={onDenied} />}
  </div>;
}

function Members({ client, onDenied }: { client: ApiClient; onDenied: () => void }) {
  const [members, setMembers] = useState<ManagedUser[]>();
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  function failed(e: unknown) {
    if (e instanceof ApiError && e.accessDenied) onDenied();
    else setError('Не удалось обновить участников. Повторите загрузку.');
  }
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    client.users(controller.signal).then(list => { if (!controller.signal.aborted) setMembers(list); })
      .catch(e => { if (!controller.signal.aborted) failed(e); });
    return () => controller.abort();
  }, [client, attempt]);
  async function update(member: ManagedUser, changes: { active?: boolean; role?: 'admin' | 'member' }) {
    if (sending.current) return;
    if (!window.confirm(`Изменить доступ участника «${member.display_name}»?`)) return;
    sending.current = true; setBusy(true); setError('');
    try { const result = await client.updateUser(member.telegram_user_id, changes); setMembers(list => list?.map(m => m.telegram_user_id === result.telegram_user_id ? result : m)); }
    catch (e) { failed(e); }
    finally { sending.current = false; setBusy(false); }
  }
  async function add(e: FormEvent) {
    e.preventDefault();
    if (sending.current) return;
    if (!/^[1-9]\d*$/.test(id) || !Number.isSafeInteger(Number(id)) || !name.trim()) { setError('Укажите числовой Telegram ID и имя.'); return; }
    sending.current = true; setBusy(true); setError('');
    try { const member = await client.createUser({ telegram_user_id: Number(id), display_name: name.trim(), role: 'member', active: true }); setMembers(list => [...(list ?? []), member]); setId(''); setName(''); }
    catch (e) { failed(e); }
    finally { sending.current = false; setBusy(false); }
  }
  return <section className="home-card"><h2>Участники</h2>
    {!members && !error && <p role="status">Загружаем участников…</p>}
    {error && <><p role="alert">{error}</p><button className="secondary-button" disabled={busy} onClick={() => setAttempt(n => n + 1)}>Повторить загрузку</button></>}
    {members?.map(member => <div className="member-row" key={member.telegram_user_id}><p>{member.display_name} · {member.role === 'admin' ? 'Администратор' : 'Участник'} · {member.active ? 'Доступ включён' : 'Доступ отключён'}</p>
      <button className="secondary-button" disabled={busy} onClick={() => update(member, { active: !member.active })}>{member.active ? 'Отключить' : 'Включить'} доступ: {member.display_name}</button>
      <button className="secondary-button" disabled={busy} onClick={() => update(member, { role: member.role === 'admin' ? 'member' : 'admin' })}>Изменить роль: {member.display_name}</button>
    </div>)}
    {members && <form onSubmit={add}><h3>Добавить участника</h3><fieldset disabled={busy}>
      <label>Telegram ID<input required inputMode="numeric" value={id} onChange={e => setId(e.target.value)} /></label>
      <label>Имя<input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></label>
      <button className="primary-button">Добавить участника</button>
    </fieldset></form>}
  </section>;
}
