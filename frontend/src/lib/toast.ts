/**
 * Notifications discrètes (`L03-09`).
 *
 * Volontairement minimal : un message, un ton, une durée. Ce qui doit être lu et
 * confirmé n'est pas une notification mais une modale ou un message de formulaire — une
 * notification qui disparaît ne doit jamais porter une information qu'on ne peut pas
 * retrouver.
 */

import { createContext, useContext } from 'react';

import type { Tone } from '@/components/ui/primitives';

export interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

export interface ToastContextValue {
  toasts: readonly Toast[];
  notify: (message: string, tone?: Tone) => void;
  dismiss: (id: number) => void;
}

export const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (value === null) {
    throw new Error("useToast doit être utilisé à l'intérieur de <Toaster>.");
  }
  return value;
}
