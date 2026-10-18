// src/pages/public/ForgotPage.tsx
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { Dumbbell, Mail, CheckCircle2, ArrowRight } from 'lucide-react';
import { client } from '../../api/client';

export const ForgotPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const forgotMutation = useMutation({
    mutationFn: async () => {
      await client.post('/auth/forgot-password', { email: email.trim() });
    },
    onSuccess: () => {
      setSubmitted(true);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    forgotMutation.mutate();
  };

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-base p-4">
      <div className="w-full max-w-md space-y-6 rounded-2xl border border-border bg-surface p-8 shadow-sm">
        <div className="text-center space-y-2">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
            <Dumbbell className="h-6 w-6" />
          </div>
          <h2 className="text-2xl font-bold text-text-primary">Reset Password</h2>
          <p className="text-xs text-text-muted">
            Enter your account email to receive a secure recovery link.
          </p>
        </div>

        {submitted ? (
          <div className="space-y-4 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-accent/15 text-accent">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <p className="text-sm text-text-primary">
              If an account with <span className="font-semibold">{email}</span> exists, a password reset link has been dispatched.
            </p>
            <div className="pt-2">
              <Link
                to="/login"
                className="inline-flex items-center gap-1.5 min-h-[44px] text-xs font-semibold text-accent hover:underline"
              >
                <span>Return to Sign In</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-text-primary mb-1">
                Account Email
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

            <button
              type="submit"
              disabled={forgotMutation.isPending}
              className="w-full min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover py-3 text-sm font-semibold text-white shadow-sm transition disabled:opacity-50"
            >
              {forgotMutation.isPending ? 'Sending...' : 'Send Recovery Link'}
            </button>

            <div className="text-center pt-2">
              <Link to="/login" className="text-xs text-text-muted hover:text-text-primary min-h-[44px] inline-flex items-center">
                Cancel and return to sign in
              </Link>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};
