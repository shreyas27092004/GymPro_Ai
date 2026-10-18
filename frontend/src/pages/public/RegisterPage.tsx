// src/pages/public/RegisterPage.tsx
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import {
  Dumbbell,
  User,
  Activity,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  Mail,
  Lock,
} from 'lucide-react';
import { client } from '../../api/client';
import type { UserRole } from '../../types';

export const RegisterPage: React.FC = () => {
  const [role, setRole] = useState<UserRole>('USER');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [termsAccepted, setTermsAccepted] = useState(false);

  // Trainer fields
  const [specializations, setSpecializations] = useState<string>('STRENGTH, HIIT');
  const [certifications, setCertifications] = useState<string>('CSCS, CPR');
  const [bio, setBio] = useState('');

  const [submitted, setSubmitted] = useState(false);
  const [registeredRole, setRegisteredRole] = useState<UserRole>('USER');

  const registerMutation = useMutation({
    mutationFn: async () => {
      const payload: any = {
        email: email.trim(),
        full_name: fullName.trim(),
        password,
        role,
        terms_accepted: termsAccepted,
      };

      if (role === 'TRAINER') {
        payload.specializations = specializations
          .split(',')
          .map((s) => s.trim().toUpperCase())
          .filter(Boolean);
        payload.certifications = certifications
          .split(',')
          .map((c) => c.trim().toUpperCase())
          .filter(Boolean);
        payload.bio = bio.trim();
      }

      const res = await client.post('/auth/register', payload);
      return res.data;
    },
    onSuccess: () => {
      setRegisteredRole(role);
      setSubmitted(true);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!termsAccepted) return;
    registerMutation.mutate();
  };

  if (submitted) {
    return (
      <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-slate-50 dark:bg-slate-950 p-4">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-8 shadow-sm text-center space-y-4">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="h-8 w-8" />
          </div>

          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Verification Email Sent</h2>

          <p className="text-sm text-slate-600 dark:text-slate-400">
            We have dispatched a verification email to <span className="font-semibold text-slate-800 dark:text-slate-200">{email}</span>.
          </p>

          <div className="rounded-xl bg-slate-50 dark:bg-slate-800/60 p-4 text-xs text-left text-slate-600 dark:text-slate-300 space-y-2">
            <p className="font-semibold text-slate-800 dark:text-slate-200">Next Steps:</p>
            {registeredRole === 'USER' && (
              <p>Click the link in the email to activate your account. You will then be guided to complete your onboarding profile.</p>
            )}
            {registeredRole === 'TRAINER' && (
              <p>Click the link to verify your email. Once verified, your credentials and background will be reviewed by gym management.</p>
            )}
            {registeredRole === 'ADMIN' && (
              <p>Click the link to verify your email. An activation code has been securely sent to all existing gym administrators for verification.</p>
            )}
          </div>

          <div className="pt-2">
            <Link
              to="/login"
              className="inline-flex items-center justify-center min-h-[44px] w-full rounded-xl bg-accent hover:bg-accent-hover py-3 text-sm font-semibold text-white transition"
            >
              Return to Sign In
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-base py-12 px-4 sm:px-6 lg:px-8">
      <div className="w-full max-w-lg space-y-8 rounded-2xl border border-border bg-surface p-8 shadow-sm">
        <div className="text-center space-y-2">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
            <Dumbbell className="h-6 w-6" />
          </div>
          <h2 className="text-3xl font-extrabold tracking-tight text-text-primary">
            Create an Account
          </h2>
          <p className="text-sm text-text-muted">
            Choose your role and join the GymPro AI network
          </p>
        </div>

        {/* Role Selector Tabs */}
        <div className="grid grid-cols-3 gap-2 rounded-xl bg-surface-raised p-1">
          <button
            type="button"
            onClick={() => setRole('USER')}
            className={`flex flex-col items-center justify-center min-h-[44px] rounded-lg py-2 text-xs font-semibold transition ${
              role === 'USER'
                ? 'bg-surface text-accent shadow-sm'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            <User className="h-4 w-4 mb-1" />
            <span>Member</span>
          </button>

          <button
            type="button"
            onClick={() => setRole('TRAINER')}
            className={`flex flex-col items-center justify-center min-h-[44px] rounded-lg py-2 text-xs font-semibold transition ${
              role === 'TRAINER'
                ? 'bg-surface text-accent shadow-sm'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            <Activity className="h-4 w-4 mb-1" />
            <span>Trainer</span>
          </button>

          <button
            type="button"
            onClick={() => setRole('ADMIN')}
            className={`flex flex-col items-center justify-center min-h-[44px] rounded-lg py-2 text-xs font-semibold transition ${
              role === 'ADMIN'
                ? 'bg-surface text-accent shadow-sm'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            <ShieldCheck className="h-4 w-4 mb-1" />
            <span>Admin</span>
          </button>
        </div>

        {registerMutation.isError && (
          <div className="flex items-center gap-2 rounded-xl bg-danger/10 border border-danger/20 p-3 text-xs text-danger">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>
              {(registerMutation.error as any)?.message ||
                'Unable to create account. Please check your information and try again.'}
            </span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-text-primary mb-1">
              Full Name
            </label>
            <input
              type="text"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Rahul Sharma"
              className="w-full min-h-[44px] rounded-xl border border-border bg-surface-raised px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
          </div>

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
            <label className="block text-xs font-semibold text-text-primary mb-1">
              Password
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

          {/* Trainer Fields */}
          {role === 'TRAINER' && (
            <div className="space-y-4 rounded-xl border border-accent/20 bg-accent/5 p-4">
              <h4 className="text-xs font-bold text-accent">
                Trainer Credentials
              </h4>

              <div>
                <label className="block text-xs font-medium text-text-primary mb-1">
                  Specializations (comma-separated)
                </label>
                <input
                  type="text"
                  value={specializations}
                  onChange={(e) => setSpecializations(e.target.value)}
                  placeholder="STRENGTH, HIIT, YOGA"
                  className="w-full min-h-[44px] rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-text-primary mb-1">
                  Certifications (comma-separated)
                </label>
                <input
                  type="text"
                  value={certifications}
                  onChange={(e) => setCertifications(e.target.value)}
                  placeholder="CSCS, NASM-CPT"
                  className="w-full min-h-[44px] rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-text-primary mb-1">
                  Short Bio / Coaching Experience
                </label>
                <textarea
                  rows={2}
                  value={bio}
                  onChange={(e) => setBio(e.target.value)}
                  placeholder="Briefly describe your coaching background and specialty areas"
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs text-text-primary"
                />
              </div>
            </div>
          )}

          {/* Admin Notice */}
          {role === 'ADMIN' && (
            <div className="rounded-xl border border-border bg-surface-raised p-4 text-xs text-text-muted">
              <div className="flex gap-2">
                <ShieldCheck className="h-5 w-5 shrink-0 text-accent" />
                <p>
                  Security Policy: Administrator activation requires approval via a one-time cryptographic code sent to active administrators. You will enter this code upon logging in.
                </p>
              </div>
            </div>
          )}

          <div className="flex items-center gap-2 pt-2">
            <input
              type="checkbox"
              id="terms"
              required
              checked={termsAccepted}
              onChange={(e) => setTermsAccepted(e.target.checked)}
              className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
            />
            <label htmlFor="terms" className="text-xs text-text-muted">
              I agree to the GymPro Terms of Service and Privacy Policy
            </label>
          </div>

          <button
            type="submit"
            disabled={registerMutation.isPending || !termsAccepted}
            className="w-full min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover py-3 text-sm font-semibold text-white shadow-sm transition disabled:opacity-50"
          >
            {registerMutation.isPending ? 'Creating Account...' : 'Create Account'}
          </button>
        </form>

        <p className="text-center text-xs text-text-muted">
          Already have an account?{' '}
          <Link to="/login" className="font-semibold text-accent hover:underline min-h-[44px] inline-flex items-center">
            Sign In
          </Link>
        </p>
      </div>
    </div>
  );
};
