// src/pages/public/VerifyPage.tsx
import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CheckCircle2, XCircle, ArrowRight, Loader2 } from 'lucide-react';
import { client } from '../../api/client';

export const VerifyPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [loading, setLoading] = useState(true);
  const [success, setSuccess] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [accountRole, setAccountRole] = useState<string>('');

  useEffect(() => {
    if (!token) {
      setLoading(false);
      setErrorMsg('No verification token provided in URL.');
      return;
    }

    const verify = async () => {
      try {
        const res = await client.post('/auth/verify-email', { token });
        setSuccess(true);
        setAccountRole(res.data?.role || 'USER');
      } catch (e: any) {
        setSuccess(false);
        setErrorMsg(
          e?.response?.data?.detail?.error ||
            e?.response?.data?.detail ||
            'Verification link is invalid or has expired.'
        );
      } finally {
        setLoading(false);
      }
    };

    verify();
  }, [token]);

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-slate-50 dark:bg-slate-950 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-8 shadow-sm text-center space-y-6">
        {loading ? (
          <div className="space-y-4 py-8">
            <Loader2 className="h-10 w-10 animate-spin text-emerald-500 mx-auto" />
            <h2 className="text-xl font-bold text-slate-900 dark:text-white">Verifying Email Address...</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Please wait while we validate your verification token.
            </p>
          </div>
        ) : success ? (
          <div className="space-y-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-8 w-8" />
            </div>

            <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Email Verified!</h2>

            {accountRole === 'USER' && (
              <p className="text-sm text-slate-600 dark:text-slate-400">
                Your email has been confirmed. You may now sign in and complete your fitness onboarding questionnaire.
              </p>
            )}

            {accountRole === 'TRAINER' && (
              <div className="rounded-xl bg-blue-50 dark:bg-blue-950/40 p-4 text-xs text-blue-800 dark:text-blue-300 text-left space-y-1">
                <p className="font-semibold">Trainer Application Queued</p>
                <p>
                  Your email is confirmed. Your profile and credentials are now awaiting review by gym administration. You will receive an email once approved.
                </p>
              </div>
            )}

            {accountRole === 'ADMIN' && (
              <div className="rounded-xl bg-purple-50 dark:bg-purple-950/40 p-4 text-xs text-purple-800 dark:text-purple-300 text-left space-y-1">
                <p className="font-semibold">Admin Authorization Code Sent</p>
                <p>
                  Your email is verified. A 6-digit one-time activation code has been dispatched to existing administrators. Enter it during sign-in to activate your account.
                </p>
              </div>
            )}

            <div className="pt-4">
              <Link
                to="/login"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 py-3 text-sm font-semibold text-white transition"
              >
                <span>Proceed to Sign In</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-red-100 dark:bg-red-950/60 text-red-600 dark:text-red-400">
              <XCircle className="h-8 w-8" />
            </div>

            <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Verification Failed</h2>

            <p className="text-sm text-red-600 dark:text-red-400">{errorMsg}</p>

            <div className="pt-4">
              <Link
                to="/login"
                className="inline-block w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 py-3 text-sm font-semibold text-slate-800 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition"
              >
                Return to Sign In
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
