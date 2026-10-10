const paths = {
  food: 'M7 3v7m3-7v7M4 3v7c0 3 9 3 9 0V3M8.5 13v16M23 3c-5 5-5 12 0 13v13M23 3v13',
  basket: 'M3 12h26l-4 15H7L3 12Zm6 0 5-9m9 9-5-9M10 17v6m6-6v6m6-6v6',
  house: 'm2 15 14-12 14 12M6 12v17h20V12M13 29V18h7v11',
  car: 'm6 12 3-7h14l3 7M3 12h26v12H3V12Zm4 12v4m18-4v4M7 17h3m12 0h3',
  travel: 'M8 3h16v21H8V3Zm0 7h16M12 6h8m-8 18-4 5m12-5 4 5M12 18h1m6 0h1',
  health: 'M11 4h10v8h8v9h-8v8H11v-8H3v-9h8V4Z',
  shirt: 'm10 4-8 6 5 7 4-3v15h12V14l4 3 5-7-8-6c-3 5-11 5-14 0Z',
  gift: 'M3 12h26v6H3v-6Zm3 6v11h20V18M16 12v17m0-17C1 12 7-3 16 12Zm0 0C31 12 25-3 16 12Z',
  phone: 'm7 3 5 6-4 4c3 5 6 8 11 11l4-4 6 5c-4 10-12 5-19-2S-2 7 7 3Z',
  sport: 'M19 4a3 3 0 1 0 0 .1M4 12l9-4 6 7 8-5M14 10l-4 11-5 7m7-11 8 5-2 7',
  pet: 'M8 14c-4-6-7-3-5 3l2 3v9h4v-7h13v7h4V18l3-5-6-2-4 6H9M25 9V5',
  other: 'M4 7h24v22H4V7Zm6-4v8m12-8v8M9 17h14m-14 6h8',
  home: 'm3 14 13-11 13 11M7 12v17h18V12M13 29V18h6v11',
  list: 'M10 7h18M10 16h18M10 25h18M4 7h1m-1 9h1m-1 9h1',
  chart: 'M5 29V17h5v12m6 0V9h5v20m6 0V3h5v26',
  settings: 'M4 8h24M4 24h24M11 4v8m10 8v8M4 16h24M16 12v8',
} as const;
export type IconName = keyof typeof paths;
export function categoryIcon(name: string): IconName {
  const value = name.toLowerCase();
  if (/продукт|магазин|покупк/.test(value)) return 'basket';
  if (/еда|питан|кафе|ресторан/.test(value)) return 'food';
  if (/дом|жиль|кварт|коммун/.test(value)) return 'house';
  if (/авто|машин|такси|бензин/.test(value)) return 'car';
  if (/транспорт|поезд|путеше|отпуск/.test(value)) return 'travel';
  if (/здоров|мед|аптек/.test(value)) return 'health';
  if (/одеж|обув/.test(value)) return 'shirt';
  if (/подар/.test(value)) return 'gift';
  if (/связ|телефон|интернет/.test(value)) return 'phone';
  if (/спорт|развлеч/.test(value)) return 'sport';
  if (/живот|питом|кот|собак/.test(value)) return 'pet';
  return 'other';
}
export const categoryColors = [
  '#ff5a67', '#3b9eff', '#ffda47', '#aa7dff', '#38d996',
  '#ff963d', '#45d9ee', '#f65ac6', '#bce345', '#c89b63',
  '#bcc7dc', '#6573ff', '#ffb7a0',
];
export function FinanceIcon({ name, className = '' }: { name: IconName; className?: string }) {
  return <svg className={className} viewBox="0 0 34 34" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
