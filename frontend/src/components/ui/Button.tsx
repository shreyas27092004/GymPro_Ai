// src/components/ui/Button.tsx
import React from 'react';
import { Loader2 } from 'lucide-react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  className = '',
  children,
  ...props
}) => {
  const baseClasses =
    'inline-flex items-center justify-center font-semibold transition-all duration-200 select-none min-h-[44px] rounded-sm focus-visible:outline-none';

  const sizeClasses = {
    sm: 'px-3 py-1.5 text-xs min-h-[38px] sm:min-h-[44px]',
    md: 'px-4 py-2.5 text-sm min-h-[44px]',
    lg: 'px-6 py-3.5 text-base min-h-[48px]',
  }[size];

  const variantClasses = {
    primary:
      'bg-accent hover:bg-accent-hover text-white shadow-sm disabled:opacity-50 active:scale-[0.98]',
    secondary:
      'border border-border bg-surface hover:bg-surface-raised text-text-primary shadow-sm disabled:opacity-50 active:scale-[0.98]',
    danger:
      'bg-danger hover:opacity-90 text-white shadow-sm disabled:opacity-50 active:scale-[0.98]',
    ghost:
      'text-text-muted hover:text-text-primary hover:bg-surface-raised disabled:opacity-50',
  }[variant];

  return (
    <button
      disabled={disabled || loading}
      className={`${baseClasses} ${sizeClasses} ${variantClasses} ${className}`}
      {...props}
    >
      {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin shrink-0" />}
      {children}
    </button>
  );
};
