// src/pages/public/ResetPasswordPage.tsx
import React, { useState } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { Dumbbell, Lock, CheckCircle2, AlertCircle } from 'lucide-react';
import { client } from '../../api/client';

export const ResetPasswordPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const navigate = useNavigate();

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [success, setSuccess] = useState(false);

  const resetMutation = useMutation({
    mutationFn: async () => {
      setErrorMsg('');
      if (password !== confirmPassword) {
        throw new Error('Passwords do not match');
      }
      await client.post('/auth/reset-password', {
        token,
        new_password: password,
      });
    },
    onSuccess: () => {
      setSuccess(true);
      setTimeout(() => navigate('/login'), 2500);
    },
    onError: (e: any) => {
      setErrorMsg(e?.response?.data?.detail?.error || e?.message || 'Failed to reset password.');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    resetMutation.mutate();
  };

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-base p-4">
      <div className="w-full max-w-md space-y-6 rounded-2xl border border-border bg-surface p-8 shadow-sm">
        <div className="text-center space-y-2">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
            <Dumbbell className="h-6 w-6" />
          </div>
          <h2 className="text-2xl font-bold text-text-primary">Choose New Password</h2>
          <p className="text-xs text-text-muted">
            Enter a strong new password for your account.
          </p>
        </div>

        {errorMsg && (
          <div className="flex items-center gap-2 rounded-xl bg-danger/10 border border-danger/20 p-3 text-xs text-danger">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {success ? (
          <div className="space-y-4 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-accent/15 text-accent">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <p className="text-sm font-semibold text-text-primary">
              Password successfully updated! Redirecting to sign in...
            </p>
            <div className="pt-2">
              <Link to="/login" className="min-h-[44px] inline-flex items-center text-xs text-accent hover:underline">
                Sign in now
              </Link>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-text-primary mb-1">
                New Password
              </label>
              <div className="relative">
                <input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Minimum 8 characters"
                  className="w-full min-h-[44px] rounded-xl border border-border bg-surface-raised pl-10 pr-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                />
                <Lock className="absolute left-3 top-3.5 h-4 w-4 text-text-muted" />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-text-primary mb-1">
                Confirm New Password
              </label>
              <div className="relative">
                <input
                  type="password"
                  required
                  minLength={8}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Repeat new password"
                  className="w-full min-h-[44px] rounded-xl border border-border bg-surface-raised pl-10 pr-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                />
                <Lock className="absolute left-3 top-3.5 h-4 w-4 text-text-muted" />
              </div>
            </div>

            <button
              type="submit"
              disabled={resetMutation.isPending || !token}
              className="w-full min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover py-3 text-sm font-semibold text-white shadow-sm transition disabled:opacity-50"
            >
              {resetMutation.isPending ? 'Updating...' : 'Set New Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};
