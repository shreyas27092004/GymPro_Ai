// src/components/ui/Drawer.tsx
import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  headerContent?: React.ReactNode;
  children: React.ReactNode;
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  headerContent,
  children,
}) => {
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      const focusables = drawerRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusables && focusables.length > 0) {
        focusables[0].focus();
      }
    }

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm transition-opacity"
      role="region"
      aria-label={title}
    >
      <div
        ref={drawerRef}
        className="w-full sm:max-w-lg h-full flex flex-col bg-surface border-l border-border shadow-2xl transition-transform duration-300 animate-in slide-in-from-right"
      >
        <header className="flex items-center justify-between border-b border-border bg-surface-raised/50 px-4 py-3">
          <div className="flex-1">
            <h2 className="text-base font-bold text-text-primary">{title}</h2>
            {headerContent}
          </div>
          <button
            onClick={onClose}
            aria-label="Close drawer"
            className="rounded-sm p-2 text-text-muted hover:bg-surface-raised transition"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
};
