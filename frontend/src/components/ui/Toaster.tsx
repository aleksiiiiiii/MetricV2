import { useCallback, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { cx } from '@/lib/cx';
import type { Tone } from '@/components/ui/primitives';
import { ToastContext, type Toast } from '@/lib/toast';

import styles from './Toaster.module.css';

const LIFETIME_MS = 5000;

/** Zone de notifications, montée une seule fois autour de l'application. */
export function Toaster({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    (message: string, tone: Tone = 'signal') => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, message, tone }]);
      // Une notification qui s'éternise devient du décor : elle s'efface seule.
      setTimeout(() => {
        dismiss(id);
      }, LIFETIME_MS);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toasts, notify, dismiss }), [toasts, notify, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.zone} role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={cx(styles.toast, styles[toast.tone])}>
            <span>{toast.message}</span>
            <button
              type="button"
              className={styles.close}
              aria-label="Fermer"
              onClick={() => {
                dismiss(toast.id);
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
