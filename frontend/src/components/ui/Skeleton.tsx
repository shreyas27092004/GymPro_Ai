// src/components/ui/Skeleton.tsx
import React from 'react';

export const Skeleton: React.FC<{ className?: string }> = ({ className = 'h-4 w-full' }) => {
  return (
    <div
      className={`animate-pulse rounded-sm bg-surface-raised ${className}`}
      aria-hidden="true"
    />
  );
};
