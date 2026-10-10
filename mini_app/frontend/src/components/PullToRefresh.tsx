import { ReactNode, useEffect, useRef, useState } from 'react';

const threshold = 72;
export function PullToRefresh({ children, disabled, onRefresh }: { children: ReactNode; disabled: boolean; onRefresh: () => void }) {
  const container = useRef<HTMLDivElement>(null);
  const latest = useRef({ disabled, onRefresh });
  latest.current = { disabled, onRefresh };
  const [distance, setDistance] = useState(0);
  useEffect(() => {
    const element = container.current!;
    let start: { x: number; y: number } | null = null;
    let pull = 0;
    const reset = () => { start = null; pull = 0; setDistance(0); };
    const begin = (event: TouchEvent) => {
      reset();
      if (latest.current.disabled || window.scrollY > 0 || event.touches.length !== 1
          || (event.target instanceof Element && event.target.closest('button, input, select, textarea, a, [role="dialog"]'))) return;
      start = { x: event.touches[0].clientX, y: event.touches[0].clientY };
    };
    const move = (event: TouchEvent) => {
      if (!start) return;
      if (latest.current.disabled || event.touches.length !== 1 || window.scrollY > 0) { reset(); return; }
      const dy = event.touches[0].clientY - start.y;
      const dx = Math.abs(event.touches[0].clientX - start.x);
      if (dy < 0 || dx > Math.max(12, dy)) { reset(); return; }
      if (dy > 8 && event.cancelable) event.preventDefault();
      pull = Math.min(100, dy * .5);
      setDistance(pull);
    };
    const end = () => {
      const refresh = start !== null && pull >= threshold && !latest.current.disabled;
      reset();
      if (refresh) latest.current.onRefresh();
    };
    element.addEventListener('touchstart', begin, { passive: true });
    element.addEventListener('touchmove', move, { passive: false });
    element.addEventListener('touchend', end);
    element.addEventListener('touchcancel', reset);
    return () => {
      element.removeEventListener('touchstart', begin);
      element.removeEventListener('touchmove', move);
      element.removeEventListener('touchend', end);
      element.removeEventListener('touchcancel', reset);
    };
  }, []);
  return <div className="pull-to-refresh" ref={container}>
    <button className="keyboard-refresh" disabled={disabled} onClick={onRefresh}>Обновить транзакции</button>
    <div className="pull-indicator" style={{ height: distance }} role="status">{distance > 0 && (distance >= threshold ? 'Отпустите, чтобы обновить' : 'Потяните вниз для обновления')}</div>
    {children}
  </div>;
}
