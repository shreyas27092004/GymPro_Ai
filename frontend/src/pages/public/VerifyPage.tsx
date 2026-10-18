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
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-base p-4">
      <div className="w-full max-w-md rounded-2xl border border-border bg-surface p-8 shadow-sm text-center space-y-6">
        {loading ? (
          <div className="space-y-4 py-8">
            <Loader2 className="h-10 w-10 animate-spin text-accent mx-auto" />
            <h2 className="text-xl font-bold text-text-primary">Verifying Email Address...</h2>
            <p className="text-sm text-text-muted">
              Please wait while we validate your verification token.
            </p>
          </div>
        ) : success ? (
          <div className="space-y-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-accent/15 text-accent">
              <CheckCircle2 className="h-8 w-8" />
            </div>

            <h2 className="text-2xl font-bold text-text-primary">Email Verified!</h2>

            {accountRole === 'USER' && (
              <p className="text-sm text-text-muted">
                Your email has been confirmed. You may now sign in and complete your fitness onboarding questionnaire.
              </p>
            )}

            {accountRole === 'TRAINER' && (
              <div className="rounded-xl bg-accent/10 p-4 text-xs text-accent text-left space-y-1">
                <p className="font-semibold">Trainer Application Queued</p>
                <p>
                  Your email is confirmed. Your profile and credentials are now awaiting review by gym administration. You will receive an email once approved.
                </p>
              </div>
            )}

            {accountRole === 'ADMIN' && (
              <div className="rounded-xl bg-accent/10 p-4 text-xs text-accent text-left space-y-1">
                <p className="font-semibold">Admin Authorization Code Sent</p>
                <p>
                  Your email is verified. A 6-digit one-time activation code has been dispatched to existing administrators. Enter it during sign-in to activate your account.
                </p>
              </div>
            )}

            <div className="pt-4">
              <Link
                to="/login"
                className="inline-flex w-full items-center justify-center gap-2 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover py-3 text-sm font-semibold text-white transition"
              >
                <span>Proceed to Sign In</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-danger/15 text-danger">
              <XCircle className="h-8 w-8" />
            </div>

            <h2 className="text-2xl font-bold text-text-primary">Verification Failed</h2>

            <p className="text-sm text-danger">{errorMsg}</p>

            <div className="pt-4">
              <Link
                to="/login"
                className="inline-flex items-center justify-center w-full min-h-[44px] rounded-xl border border-border bg-surface py-3 text-sm font-semibold text-text-primary hover:bg-surface-raised transition"
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
