// src/auth/RequireRole.tsx
import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useMe } from './useMe';
import { homeFor } from './AuthContext';
import type { UserRole } from '../types';

export const RequireRole: React.FC<{ roles: UserRole[] }> = ({ roles }) => {
  const { me, isLoading } = useMe();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950 text-slate-600 dark:text-slate-300">
        <div className="text-center space-y-2">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-emerald-500 border-r-transparent align-[-0.125em]" />
          <p className="text-sm font-medium">Verifying session...</p>
        </div>
      </div>
    );
  }

  if (!me) {
    return <Navigate to="/login" replace />;
  }

  if (me.account_status !== 'ACTIVE') {
    return <Navigate to="/login" replace />;
  }

  return roles.includes(me.role) ? <Outlet /> : <Navigate to={homeFor(me.role)} replace />;
};
