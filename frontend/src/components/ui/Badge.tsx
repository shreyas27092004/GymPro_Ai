// src/components/ui/Badge.tsx
import React from 'react';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'accent' | 'neutral' | 'danger' | 'warning';
  children: React.ReactNode;
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'neutral',
  children,
  className = '',
  ...props
}) => {
  const variantClasses = {
    accent:
      'bg-accent-subtle text-accent border border-accent/20 font-bold',
    neutral:
      'bg-surface-raised text-text-muted border border-border font-medium',
    danger:
      'bg-danger-subtle text-danger border border-danger/20 font-bold',
    warning:
      'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200 border border-amber-300 dark:border-amber-800 font-bold',
  }[variant];

  return (
    <span
      className={`inline-flex items-center rounded-sm px-2.5 py-0.5 text-xs uppercase tracking-wider ${variantClasses} ${className}`}
      {...props}
    >
      {children}
    </span>
  );
};
