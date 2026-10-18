// src/components/ui/Card.tsx
import React from 'react';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  elevation?: 'flat' | 'raised';
}

export const Card: React.FC<CardProps> = ({
  children,
  elevation = 'flat',
  className = '',
  ...props
}) => {
  const elevationClasses =
    elevation === 'raised'
      ? 'bg-surface-raised border border-border shadow-md'
      : 'bg-surface border border-border shadow-sm';

  return (
    <div className={`rounded-md p-6 ${elevationClasses} ${className}`} {...props}>
      {children}
    </div>
  );
};
