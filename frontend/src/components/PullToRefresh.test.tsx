import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { PullToRefresh } from './PullToRefresh';

function start(target: HTMLElement, x = 100, y = 100) { fireEvent.touchStart(target, { touches: [{ clientX: x, clientY: y }] }); }
function move(target: HTMLElement, x = 100, y = 270) { fireEvent.touchMove(target, { touches: [{ clientX: x, clientY: y }] }); }
function setup(disabled = false) {
  const refresh = vi.fn();
  const view = render(<PullToRefresh disabled={disabled} onRefresh={refresh}><div data-testid="surface">Список</div><input aria-label="Поиск" /></PullToRefresh>);
  return { refresh, target: screen.getByTestId('surface'), ...view };
}
it('обновляет только после отпускания и только один раз', () => {
  const { refresh, target } = setup();
  start(target); move(target);
  expect(screen.getByRole('status')).toHaveTextContent('Отпустите');
  expect(refresh).not.toHaveBeenCalled();
  fireEvent.touchEnd(target); fireEvent.touchEnd(target);
  expect(refresh).toHaveBeenCalledOnce();
});
it('игнорирует короткий, горизонтальный, отменённый жест и ввод в поле', () => {
  const { refresh, target } = setup();
  start(target); move(target, 100, 150); fireEvent.touchEnd(target);
  start(target); move(target, 300, 140); fireEvent.touchEnd(target);
  start(target); move(target); fireEvent.touchCancel(target); fireEvent.touchEnd(target);
  const input = screen.getByLabelText('Поиск'); start(input); move(input); fireEvent.touchEnd(input);
  expect(refresh).not.toHaveBeenCalled();
});
it('не обновляет при прокрутке ниже начала страницы или во время загрузки', () => {
  const { refresh, target, rerender } = setup();
  vi.stubGlobal('scrollY', 100); start(target); move(target); fireEvent.touchEnd(target);
  vi.stubGlobal('scrollY', 0); start(target); move(target);
  rerender(<PullToRefresh disabled onRefresh={refresh}><div data-testid="surface">Список</div></PullToRefresh>);
  fireEvent.touchEnd(target);
  expect(refresh).not.toHaveBeenCalled();
});
it('сохраняет доступное обновление с клавиатуры', () => {
  const { refresh } = setup(); fireEvent.click(screen.getByRole('button', { name: 'Обновить транзакции' }));
  expect(refresh).toHaveBeenCalledOnce();
});
