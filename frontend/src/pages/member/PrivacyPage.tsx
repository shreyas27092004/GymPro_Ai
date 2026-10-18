// src/pages/member/PrivacyPage.tsx
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Lock,
  ShieldCheck,
  Download,
  Trash2,
  CheckCircle,
  AlertTriangle,
  Brain,
} from 'lucide-react';
import { client, friendlyError } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';

export const PrivacyPage: React.FC = () => {
  const { me, refreshMe, logout } = useAuth();
  const queryClient = useQueryClient();

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // 1. Fetch AI Memory Snapshot
  const { data: memoryData } = useQuery({
    queryKey: ['me-memory'],
    queryFn: async () => {
      try {
        const res = await client.get('/me/memory');
        return res.data;
      } catch {
        return null;
      }
    },
  });

  // 2. Fetch Intake Profile
  const { data: intakeData } = useQuery({
    queryKey: ['me-intake'],
    queryFn: async () => {
      try {
        const res = await client.get('/me/intake');
        return res.data;
      } catch {
        return null;
      }
    },
  });

  // Consent toggle mutation
  const consentMutation = useMutation({
    mutationFn: async (newConsent: boolean) => {
      if (newConsent) {
        await client.post('/me/consent', { consent: true });
      } else {
        await client.delete('/me/consent');
      }
    },
    onSuccess: async (_, newConsent) => {
      await refreshMe();
      queryClient.invalidateQueries({ queryKey: ['me-memory'] });
      queryClient.invalidateQueries({ queryKey: ['me-intake'] });
      setStatusMsg({
        type: 'success',
        text: newConsent
          ? 'Health data consent granted. Personalized fitness guidance is now enabled.'
          : 'Health data consent withdrawn. Your biometric profile and AI memory have been purged.',
      });
    },
    onError: (e: any) => {
      setStatusMsg({
        type: 'error',
        text: friendlyError(e),
      });
    },
  });

  // Export data mutation
  const exportMutation = useMutation({
    mutationFn: async () => {
      const res = await client.post('/me/export', {});
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(res.data, null, 2));
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', `gympro_export_${Date.now()}.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    },
    onSuccess: () => {
      setStatusMsg({
        type: 'success',
        text: 'Data export generated and downloaded to your computer.',
      });
    },
  });

  // Delete all data mutation
  const deleteDataMutation = useMutation({
    mutationFn: async () => {
      await client.delete('/me/data');
      await logout();
    },
  });

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 dark:bg-slate-950 py-12 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-4xl space-y-8">
        <div>
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 mb-2">
            <Lock className="h-5 w-5" />
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 dark:text-white">
            Data Privacy & AI Memory Controls
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Review what the AI system knows about you, toggle health data consent, or download an audit export.
          </p>
        </div>

        {statusMsg && (
          <div
            className={`flex items-center gap-2.5 rounded-xl p-4 text-xs font-medium ${
              statusMsg.type === 'success'
                ? 'bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
                : 'bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-300'
            }`}
          >
            {statusMsg.type === 'success' ? (
              <CheckCircle className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <AlertTriangle className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
            )}
            <span>{statusMsg.text}</span>
          </div>
        )}

        {/* Affirmative Consent Card */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-900 dark:text-white">
                  Health & Biometric Data Consent
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Status: {me?.health_consent ? 'Active (Consented)' : 'Withdrawn / Inactive'}
                </p>
              </div>
            </div>

            <button
              onClick={() => consentMutation.mutate(!me?.health_consent)}
              disabled={consentMutation.isPending}
              className={`rounded-xl px-4 py-2 text-xs font-semibold shadow-sm transition disabled:opacity-50 ${
                me?.health_consent
                  ? 'border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-300 hover:bg-red-100'
                  : 'bg-emerald-600 hover:bg-emerald-700 text-white'
              }`}
            >
              {consentMutation.isPending
                ? 'Updating...'
                : me?.health_consent
                ? 'Withdraw Consent'
                : 'Grant Affirmative Consent'}
            </button>
          </div>

          <p className="text-xs text-slate-600 dark:text-slate-400 border-t border-slate-100 dark:border-slate-800 pt-3">
            When consent is enabled, your injuries, allergies, and metabolic targets are stored in PostgreSQL with Row-Level Security and used to prevent injury conflicts. Withdrawing consent purges your intake profile and clears AI conversation memory immediately.
          </p>
        </div>

        {/* What the AI Remembers */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-500/10 text-purple-600 dark:text-purple-400">
              <Brain className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">
                What the AI Remembers
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Transparent view of active parameters and conversation memory
              </p>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4 pt-2">
            <div className="rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-4 space-y-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Intake Profile Snapshot
              </span>
              {intakeData ? (
                <div className="text-xs space-y-1 text-slate-700 dark:text-slate-300">
                  <p><span className="font-semibold">Goal:</span> {intakeData.goal || 'General Health'}</p>
                  <p><span className="font-semibold">Experience:</span> {intakeData.experience_level || 'Beginner'}</p>
                  <p><span className="font-semibold">Known Injuries:</span> {intakeData.known_injuries?.join(', ') || 'None'}</p>
                  <p><span className="font-semibold">Allergens:</span> {intakeData.allergies?.join(', ') || 'None'}</p>
                </div>
              ) : (
                <p className="text-xs text-slate-400">No profile recorded or consent withdrawn.</p>
              )}
            </div>

            <div className="rounded-xl border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-4 space-y-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                AI Memory & Handoff State
              </span>
              {memoryData ? (
                <div className="text-xs space-y-1 text-slate-700 dark:text-slate-300">
                  <p><span className="font-semibold">Preferred Times:</span> {memoryData.preferred_times || 'Evening'}</p>
                  <p><span className="font-semibold">Active Inquiries:</span> {memoryData.active_inquiries || 'None'}</p>
                  <p><span className="font-semibold">Last Interaction:</span> {memoryData.last_interaction || 'Today'}</p>
                </div>
              ) : (
                <p className="text-xs text-slate-400">Conversation context is clear.</p>
              )}
            </div>
          </div>
        </div>

        {/* Data Portability & Erasure */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-6">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white">
              Data Portability & Account Erasure
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Download your full data archive or delete your entire account per GDPR Article 17.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-4">
            <button
              onClick={() => exportMutation.mutate()}
              disabled={exportMutation.isPending}
              className="w-full sm:w-auto flex items-center justify-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-2.5 text-xs font-semibold text-slate-800 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              <span>{exportMutation.isPending ? 'Generating...' : 'Export My Data (JSON)'}</span>
            </button>

            <button
              onClick={() => setConfirmDelete(true)}
              className="w-full sm:w-auto flex items-center justify-center gap-2 rounded-xl border border-red-300 dark:border-red-900/60 bg-red-50 dark:bg-red-950/20 px-4 py-2.5 text-xs font-semibold text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-950/50 transition"
            >
              <Trash2 className="h-4 w-4" />
              <span>Delete My Data</span>
            </button>
          </div>

          {confirmDelete && (
            <div className="rounded-xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-bold text-red-900 dark:text-red-200">
                <AlertTriangle className="h-4 w-4 text-red-600" />
                <span>Are you sure you want to delete your entire account and all history?</span>
              </div>
              <p className="text-xs text-red-700 dark:text-red-300">
                This action is irreversible. All memberships, booking records, intake notes, and AI interaction histories will be permanently destroyed.
              </p>
              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={() => deleteDataMutation.mutate()}
                  disabled={deleteDataMutation.isPending}
                  className="rounded-lg bg-red-600 hover:bg-red-700 px-4 py-1.5 text-xs font-semibold text-white transition disabled:opacity-50"
                >
                  {deleteDataMutation.isPending ? 'Deleting...' : 'Yes, Delete Everything'}
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="rounded-lg border border-slate-300 dark:border-slate-700 px-4 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
