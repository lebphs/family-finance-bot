import { getTelegram } from './telegram';

export interface CurrentUser {
  telegram_user_id: number;
  display_name: string;
  role: 'admin' | 'member';
}
export interface ReminderSettings {
  reminder_enabled: boolean; reminder_time: string; reminder_days: number[]; timezone: string;
}
export interface ReminderResponse extends ReminderSettings { chat_connected: boolean }
export interface ManagedUser extends CurrentUser { active: boolean }
export interface UserInput { telegram_user_id: number; display_name: string; role: 'admin' | 'member'; active: boolean }
export interface Category { name: string; subcategories: string[] }
export interface TripInput { name: string; date_from: string; date_to: string; currency: string }
export interface Trip extends TripInput { trip_id: string; created_by: number; completed: boolean }
export interface TravelContext { trip: Trip | null; currencies: string[] }
export interface TripReport { trip: Trip; total: string; count: number; categories: { category: string; amount: string }[]; participants: { author_id: number | null; author_name: string; amount: string }[]; transactions: Transaction[] }
export type ExpenseScope = 'all' | 'everyday' | 'travel';
export interface ExpenseInput { trip_id?: string | null; currency?: string; request_id: string; date: string; amount: string; category: string; description: string }
export interface Transaction {
  trip_id?: string | null; original_amount?: string | null; currency?: string; exchange_rate?: string | null; rate_date?: string | null; rate_source?: string | null;
  version?: string; transaction_id: string | null; date: string; amount: string; category: string; description: string;
  author_id: number | null; author_name: string; created_at: string | null; updated_at: string | null;
}
export interface TransactionPage { items: Transaction[]; total: number; next_offset: number | null }
export interface Participant { author_id: number | null; author_name: string }
export interface TransactionFilters { scope?: ExpenseScope; trip_id?: string; date_from?: string; date_to?: string; category?: string; author_id?: string; unknown_author?: string; search?: string; offset?: string; limit?: string }
export type TransactionEdit = Omit<ExpenseInput, "request_id"> & { version: string };

export interface HomeSummary {
  month: string; total: string; previous_total: string; change: string; change_percent: string | null;
  categories: { category: string; amount: string }[]; recent: Transaction[];
}

export interface StatisticsQuery {
  scope?: ExpenseScope;
  mode?: 'months' | 'range' | 'compare'; months?: string;
  month_from?: string; month_to?: string; compare_from?: string; compare_to?: string;
  author_id?: string; unknown_author?: string;
}
export interface MonthTotal { month: string; total: string; change: string | null; change_percent: string | null }
export interface ParticipantStatistics extends Participant {
  total: string; share_percent: string | null; count: number; average: string;
  categories: { category: string; amount: string }[]; monthly: MonthTotal[];
}
export interface StatisticsSummary {
  mode: string; months: string[]; author_id: number | null; unknown_author: boolean;
  total: string; family_total: string; count: number;
  categories: { category: string; amount: string }[]; monthly: MonthTotal[];
  participants: ParticipantStatistics[]; available_participants: Participant[];
  comparison: { month_from: string; month_to: string; from_total: string; to_total: string; change: string; change_percent: string | null } | null;
}

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(message);
    this.name = 'ApiError';
  }
  get accessDenied(): boolean { return this.status === 401 || this.status === 403; }
}

export interface AuthContext {
  initData: string;
  development: boolean;
  devAuthEnabled: boolean;
  devUserId: string;
  hostname: string;
}

export function authHeaders(auth: AuthContext): Record<string, string> {
  if (auth.initData) return { Authorization: `tma ${auth.initData}` };
  const local = auth.hostname === 'localhost' || auth.hostname === '127.0.0.1';
  if (auth.development && auth.devAuthEnabled && local && /^[1-9]\d*$/.test(auth.devUserId)
      && Number.isSafeInteger(Number(auth.devUserId))) {
    return { 'X-Dev-Telegram-User-Id': auth.devUserId };
  }
  throw new ApiError(401, 'invalid_auth', 'Откройте приложение через Telegram.');
}

function browserAuth(): AuthContext {
  return {
    initData: getTelegram()?.initData ?? '',
    development: import.meta.env.DEV,
    devAuthEnabled: import.meta.env.VITE_DEV_AUTH_ENABLED === 'true',
    devUserId: import.meta.env.VITE_DEV_TELEGRAM_USER_ID ?? '',
    hostname: window.location.hostname,
  };
}

// Relative URLs keep initData on this origin and allow one HTTPS tunnel for frontend + API.
export class ApiClient {
  constructor(private readonly auth: () => AuthContext = browserAuth,
              private readonly send: typeof fetch = (...args) => fetch(...args)) {}

  private async get<T>(path: string, signal?: AbortSignal, body?: object, method = body ? 'POST' : 'GET'): Promise<T> {
    const headers = { ...authHeaders(this.auth()), ...(body ? { 'Content-Type': 'application/json' } : {}) };
    let response: Response;
    try {
      response = await this.send(`/api/${path}`, {
        headers, signal, credentials: 'omit', redirect: 'error', cache: 'no-store',
        method, ...(body ? { body: JSON.stringify(body) } : {}),
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new ApiError(0, 'network_error', 'Не удалось связаться с сервером. Проверьте соединение.');
    }
    if (!response.ok) {
      const known: Record<string, string> = {
        rate_unavailable: 'Не удалось получить курс. Данные сохранены в форме — повторите отправку.',
        currency_unavailable: 'Нет курса для этой валюты на выбранную дату. Выберите другую валюту.',
        future_rate: 'Курс на будущую дату ещё неизвестен.',
        trip_completed: 'Поездка завершена. Добавьте расход через её карточку.',
        trip_not_found: 'Поездка не найдена.',
      };
      let code = '';
      try { code = (await response.json()).error?.code ?? ''; } catch { /* untrusted proxy response */ }
      if (known[code]) throw new ApiError(response.status, code, known[code]);
      // Do not display arbitrary server/proxy text or log response bodies/authentication data.
      throw new ApiError(response.status, response.status === 401 || response.status === 403
        ? 'access_denied' : 'request_failed', response.status === 401 || response.status === 403
        ? 'Нет доступа' : response.status === 404 ? 'Операция уже удалена или не найдена.'
        : response.status === 409 && method !== 'POST' ? 'Операция уже изменена. Загрузите актуальные данные.'
        : method === 'DELETE' ? 'Не удалось подтвердить удаление. Обновите список и проверьте результат.' : path === 'reminders' && body ? (response.status === 422 ? 'Проверьте время, дни недели и часовой пояс.' : 'Не удалось сохранить настройки. Повторите отправку.')
        : path.startsWith('admin/users') && body ? 'Не удалось сохранить участника. Проверьте данные и повторите.'
        : body ? (response.status === 422 ? 'Проверьте сумму, категорию и дату.'
          : response.status === 409 ? 'Этот запрос уже сохранён с другими данными.'
          : 'Не удалось подтвердить сохранение. Повторите отправку с теми же данными.')
        : 'Не удалось загрузить данные. Попробуйте ещё раз.');
    }
    if (response.status === 204) return undefined as T;
    try { return await response.json() as T; }
    catch { throw new ApiError(response.status, 'invalid_response', 'Сервер вернул некорректный ответ.'); }
  }

  statistics(query: StatisticsQuery = {}, signal?: AbortSignal): Promise<StatisticsSummary> {
    return this.get(`statistics?${new URLSearchParams(query as Record<string, string>)}`, signal);
  }
  reminders(signal?: AbortSignal): Promise<ReminderResponse> { return this.get('reminders', signal); }
  saveReminders(input: ReminderSettings): Promise<ReminderResponse> { return this.get('reminders', undefined, input, 'PUT'); }
  users(signal?: AbortSignal): Promise<ManagedUser[]> { return this.get('admin/users', signal); }
  createUser(input: UserInput): Promise<ManagedUser> { return this.get('admin/users', undefined, input); }
  updateUser(id: number, input: Partial<ManagedUser>): Promise<ManagedUser> {
    return this.get(`admin/users/${id}`, undefined, input, 'PATCH');
  }
  trips(signal?: AbortSignal): Promise<Trip[]> { return this.get('trips', signal); }
  createTrip(input: TripInput): Promise<Trip> { return this.get('trips', undefined, input); }
  updateTrip(id: string, input: TripInput): Promise<Trip> { return this.get(`trips/${encodeURIComponent(id)}`, undefined, input, 'PUT'); }
  completeTrip(id: string): Promise<Trip> { return this.get(`trips/${encodeURIComponent(id)}/complete`, undefined, undefined, 'POST'); }
  tripReport(id: string, signal?: AbortSignal): Promise<TripReport> { return this.get(`trips/${encodeURIComponent(id)}/report`, signal); }
  travelContext(signal?: AbortSignal): Promise<TravelContext> { return this.get('travel-mode', signal); }
  setTravelMode(trip_id: string | null): Promise<TravelContext> { return this.get('travel-mode', undefined, { trip_id }, 'PUT'); }
  me(signal?: AbortSignal): Promise<CurrentUser> { return this.get('me', signal); }
  categories(signal?: AbortSignal, travel = false): Promise<Category[]> { return this.get(travel ? 'categories?travel=true' : 'categories', signal); }
  home(signal?: AbortSignal, scope: ExpenseScope = 'everyday', month?: string): Promise<HomeSummary> {
    const query = new URLSearchParams();
    if (scope !== 'everyday') query.set('scope', scope);
    if (month) query.set('month', month);
    return this.get(`home${query.size ? `?${query}` : ''}`, signal);
  }
  transactions(filters: TransactionFilters = {}, signal?: AbortSignal): Promise<TransactionPage> {
    return this.get(`transactions?${new URLSearchParams(filters as Record<string, string>)}`, signal);
  }
  transactionCategories(signal?: AbortSignal): Promise<string[]> { return this.get('transactions/categories', signal); }
  participants(signal?: AbortSignal): Promise<Participant[]> { return this.get('transactions/participants', signal); }
  transaction(id: string): Promise<Transaction> { return this.get(`transactions/${encodeURIComponent(id)}`); }
  updateTransaction(id: string, input: TransactionEdit): Promise<Transaction> {
    return this.get(`transactions/${encodeURIComponent(id)}`, undefined, input, 'PATCH');
  }
  deleteTransaction(id: string, version: string): Promise<void> {
    return this.get(`transactions/${encodeURIComponent(id)}?${new URLSearchParams({ version })}`, undefined, undefined, 'DELETE');
  }
  createExpense(input: ExpenseInput): Promise<Transaction> { return this.get('transactions', undefined, input); }
}

export const api = new ApiClient();
