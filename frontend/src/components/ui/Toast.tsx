// src/components/ui/Toast.tsx
import React from 'react';
import { CheckCircle2, AlertCircle, X } from 'lucide-react';

export interface ToastProps {
  type?: 'success' | 'error';
  message: string;
  onDismiss: () => void;
}

export const Toast: React.FC<ToastProps> = ({
  type = 'success',
  message,
  onDismiss,
}) => {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-md p-4 shadow-xl border text-xs font-semibold animate-in slide-in-from-bottom-5 ${
        type === 'success'
          ? 'bg-surface border-accent text-accent'
          : 'bg-surface border-danger text-danger'
      }`}
    >
      {type === 'success' ? (
        <CheckCircle2 className="h-5 w-5 shrink-0" />
      ) : (
        <AlertCircle className="h-5 w-5 shrink-0" />
      )}
      <span>{message}</span>
      <button
        onClick={onDismiss}
        aria-label="Dismiss toast"
        className="ml-2 rounded p-1 hover:bg-surface-raised transition"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
};
