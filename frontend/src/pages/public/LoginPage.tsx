// src/pages/public/LoginPage.tsx
import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import {
  Dumbbell,
  Mail,
  Lock,
  KeyRound,
  AlertCircle,
  Clock,
  ArrowRight,
} from 'lucide-react';
import { client } from '../../api/client';
import { useAuth, homeFor } from '../../auth/AuthContext';
import type { UserSession } from '../../types';

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [adminCode, setAdminCode] = useState('');
  const [showAdminCodeBox, setShowAdminCodeBox] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [pendingState, setPendingState] = useState<string | null>(null);

  const loginMutation = useMutation({
    mutationFn: async () => {
      setErrorMessage('');
      setPendingState(null);

      if (showAdminCodeBox && adminCode.trim()) {
        const res = await client.post('/auth/activate-admin', {
          email: email.trim(),
          password,
          code: adminCode.trim(),
        });
        return res.data;
      } else {
        const res = await client.post('/auth/login', {
          email: email.trim(),
          password,
        });
        return res.data;
      }
    },
    onSuccess: async (data) => {
      try {
        const token = data.access_token;
        const user = await login(token, data?.session);

        if (user?.role === 'USER' && !user.health_consent) {
          navigate('/onboarding');
        } else if (user?.role) {
          navigate(homeFor(user.role));
        } else {
          navigate('/app');
        }
      } catch (err) {
        console.error('Error during post-login navigation:', err);
        navigate('/app');
      }
    },
    onError: (e: any) => {
      const err = e?.response?.data?.detail;
      const errCode = typeof err === 'object' ? err.error : err;

      if (errCode === 'ACCOUNT_PENDING_ADMIN_CODE') {
        setShowAdminCodeBox(true);
        setPendingState('ACCOUNT_PENDING_ADMIN_CODE');
        setErrorMessage('Password verified! Please enter your one-time admin activation code below.');
      } else if (errCode === 'ACCOUNT_PENDING_APPROVAL') {
        setPendingState('ACCOUNT_PENDING_APPROVAL');
        setErrorMessage('Your trainer application is currently pending administrator review.');
      } else if (errCode === 'EMAIL_NOT_VERIFIED') {
        setPendingState('EMAIL_NOT_VERIFIED');
        setErrorMessage('Your email address has not been verified. Please check your inbox for the activation link.');
      } else if (errCode === 'ACCOUNT_REJECTED') {
        setPendingState('ACCOUNT_REJECTED');
        setErrorMessage('Your application has been rejected by administration.');
      } else if (errCode === 'ACCOUNT_SUSPENDED') {
        setPendingState('ACCOUNT_SUSPENDED');
        setErrorMessage('Your account is currently suspended. Please contact gym support.');
      } else if (errCode === 'INVALID_CODE') {
        setErrorMessage('Invalid activation code. Please check your code and try again.');
      } else if (errCode === 'REQUEST_LOCKED') {
        setErrorMessage('Too many failed code attempts. This admin request has been permanently locked.');
      } else if (errCode === 'INVALID_CREDENTIALS') {
        setErrorMessage('Invalid email or password.');
      } else {
        setErrorMessage(typeof err === 'string' ? err : 'Unable to sign in. Please verify your credentials.');
      }
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loginMutation.mutate();
  };

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-base py-12 px-4 sm:px-6 lg:px-8">
      <div className="w-full max-w-md space-y-8 rounded-2xl border border-border bg-surface p-8 shadow-sm">
        <div className="text-center space-y-2">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
            <Dumbbell className="h-6 w-6" />
          </div>
          <h2 className="text-3xl font-extrabold tracking-tight text-text-primary">
            Sign In to GymPro
          </h2>
          <p className="text-sm text-text-muted">
            Access your coach, schedules, or console
          </p>
        </div>

        {errorMessage && (
          <div
            className={`flex items-start gap-2.5 rounded-xl p-3.5 text-xs ${
              pendingState === 'ACCOUNT_PENDING_ADMIN_CODE'
                ? 'bg-accent/10 border border-accent/20 text-accent'
                : pendingState === 'ACCOUNT_PENDING_APPROVAL'
                ? 'bg-amber-500/10 border border-amber-500/20 text-amber-600 dark:text-amber-400'
                : 'bg-danger/10 border border-danger/20 text-danger'
            }`}
          >
            {pendingState === 'ACCOUNT_PENDING_ADMIN_CODE' ? (
              <KeyRound className="h-4 w-4 shrink-0 text-accent mt-0.5" />
            ) : pendingState === 'ACCOUNT_PENDING_APPROVAL' ? (
              <Clock className="h-4 w-4 shrink-0 text-amber-500 mt-0.5" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0 text-danger mt-0.5" />
            )}
            <span>{errorMessage}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-text-primary mb-1">
              Email Address
            </label>
            <div className="relative">
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full min-h-[44px] rounded-xl border border-border bg-surface-raised pl-10 pr-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
              <Mail className="absolute left-3 top-3.5 h-4 w-4 text-text-muted" />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-semibold text-text-primary">
                Password
              </label>
              <Link
                to="/forgot"
                className="text-xs text-accent hover:underline"
              >
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                className="w-full min-h-[44px] rounded-xl border border-border bg-surface-raised pl-10 pr-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
              <Lock className="absolute left-3 top-3.5 h-4 w-4 text-text-muted" />
            </div>
          </div>

          {/* Admin Activation One-Time Code Box */}
          {showAdminCodeBox && (
            <div className="rounded-xl border border-border bg-surface-raised p-4 space-y-2">
              <label className="block text-xs font-bold text-text-primary">
                Admin One-Time Activation Code
              </label>
              <div className="relative">
                <input
                  type="text"
                  required
                  maxLength={12}
                  value={adminCode}
                  onChange={(e) => setAdminCode(e.target.value)}
                  placeholder="Enter 6-digit code"
                  className="w-full min-h-[44px] rounded-lg border border-border bg-surface pl-10 pr-3.5 py-2 font-mono text-sm tracking-widest text-text-primary focus:border-accent focus:outline-none"
                />
                <KeyRound className="absolute left-3 top-3.5 h-4 w-4 text-accent" />
              </div>
              <p className="text-[11px] text-text-muted">
                Enter the HMAC authorization code sent to existing administrators.
              </p>
            </div>
          )}

          <button
            type="submit"
            disabled={loginMutation.isPending}
            className="w-full min-h-[44px] flex items-center justify-center gap-2 rounded-xl bg-accent hover:bg-accent-hover py-3 text-sm font-semibold text-white shadow-sm transition disabled:opacity-50"
          >
            <span>{loginMutation.isPending ? 'Verifying...' : showAdminCodeBox ? 'Activate & Sign In' : 'Sign In'}</span>
            <ArrowRight className="h-4 w-4" />
          </button>
        </form>

        <div className="flex items-center justify-between text-xs text-text-muted pt-2 border-t border-border">
          <p>
            Don't have an account?{' '}
            <Link to="/register" className="font-semibold text-accent hover:underline">
              Register
            </Link>
          </p>

          <button
            type="button"
            onClick={() => setShowAdminCodeBox((s) => !s)}
            className="text-text-muted hover:text-text-primary hover:underline min-h-[44px] flex items-center"
          >
            {showAdminCodeBox ? 'Hide Code Box' : 'Admin Code?'}
          </button>
        </div>
      </div>
    </div>
  );
};
