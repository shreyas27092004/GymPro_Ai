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
    <div className="min-h-[calc(100vh-4rem)] bg-base text-text-primary py-12 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-4xl space-y-8">
        <div>
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent mb-2">
            <Lock className="h-5 w-5" />
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-text-primary">
            Data Privacy & AI Memory Controls
          </h1>
          <p className="text-xs text-text-muted mt-1">
            Review what the AI system knows about you, toggle health data consent, or download an audit export.
          </p>
        </div>

        {statusMsg && (
          <div
            className={`flex items-center gap-2.5 rounded-xl p-4 text-xs font-medium ${
              statusMsg.type === 'success'
                ? 'bg-accent/10 border border-accent/20 text-accent'
                : 'bg-danger/10 border border-danger/20 text-danger'
            }`}
          >
            {statusMsg.type === 'success' ? (
              <CheckCircle className="h-4 w-4 shrink-0 text-accent" />
            ) : (
              <AlertTriangle className="h-4 w-4 shrink-0 text-danger" />
            )}
            <span>{statusMsg.text}</span>
          </div>
        )}

        {/* Affirmative Consent Card */}
        <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-text-primary">
                  Health & Biometric Data Consent
                </h2>
                <p className="text-xs text-text-muted">
                  Status: {me?.health_consent ? 'Active (Consented)' : 'Withdrawn / Inactive'}
                </p>
              </div>
            </div>

            <button
              onClick={() => consentMutation.mutate(!me?.health_consent)}
              disabled={consentMutation.isPending}
              className={`min-h-[44px] rounded-xl px-4 py-2 text-xs font-semibold shadow-sm transition disabled:opacity-50 ${
                me?.health_consent
                  ? 'border border-danger/30 bg-danger/10 text-danger hover:bg-danger/20'
                  : 'bg-accent hover:bg-accent-hover text-white'
              }`}
            >
              {consentMutation.isPending
                ? 'Updating...'
                : me?.health_consent
                ? 'Withdraw Consent'
                : 'Grant Affirmative Consent'}
            </button>
          </div>

          <p className="text-xs text-text-muted border-t border-border pt-3">
            When consent is enabled, your injuries, allergies, and metabolic targets are stored in PostgreSQL with Row-Level Security and used to prevent injury conflicts. Withdrawing consent purges your intake profile and clears AI conversation memory immediately.
          </p>
        </div>

        {/* What the AI Remembers */}
        <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent">
              <Brain className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-text-primary">
                What the AI Remembers
              </h2>
              <p className="text-xs text-text-muted">
                Transparent view of active parameters and conversation memory
              </p>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4 pt-2">
            <div className="rounded-xl border border-border bg-surface-raised p-4 space-y-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                Intake Profile Snapshot
              </span>
              {intakeData ? (
                <div className="text-xs space-y-1 text-text-primary">
                  <p><span className="font-semibold">Goal:</span> {intakeData.goal || 'General Health'}</p>
                  <p><span className="font-semibold">Experience:</span> {intakeData.experience_level || 'Beginner'}</p>
                  <p><span className="font-semibold">Known Injuries:</span> {intakeData.known_injuries?.join(', ') || 'None'}</p>
                  <p><span className="font-semibold">Allergens:</span> {intakeData.allergies?.join(', ') || 'None'}</p>
                </div>
              ) : (
                <p className="text-xs text-text-muted">No profile recorded or consent withdrawn.</p>
              )}
            </div>

            <div className="rounded-xl border border-border bg-surface-raised p-4 space-y-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                AI Memory & Handoff State
              </span>
              {memoryData ? (
                <div className="text-xs space-y-1 text-text-primary">
                  <p><span className="font-semibold">Preferred Times:</span> {memoryData.preferred_times || 'Evening'}</p>
                  <p><span className="font-semibold">Active Inquiries:</span> {memoryData.active_inquiries || 'None'}</p>
                  <p><span className="font-semibold">Last Interaction:</span> {memoryData.last_interaction || 'Today'}</p>
                </div>
              ) : (
                <p className="text-xs text-text-muted">Conversation context is clear.</p>
              )}
            </div>
          </div>
        </div>

        {/* Data Portability & Erasure */}
        <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-6">
          <div>
            <h2 className="text-base font-bold text-text-primary">
              Data Portability & Account Erasure
            </h2>
            <p className="text-xs text-text-muted">
              Download your full data archive or delete your entire account per GDPR Article 17.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-4">
            <button
              onClick={() => exportMutation.mutate()}
              disabled={exportMutation.isPending}
              className="w-full sm:w-auto min-h-[44px] flex items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 py-2.5 text-xs font-semibold text-text-primary hover:bg-surface-raised transition disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              <span>{exportMutation.isPending ? 'Generating...' : 'Export My Data (JSON)'}</span>
            </button>

            <button
              onClick={() => setConfirmDelete(true)}
              className="w-full sm:w-auto min-h-[44px] flex items-center justify-center gap-2 rounded-xl border border-danger/30 bg-danger/10 px-4 py-2.5 text-xs font-semibold text-danger hover:bg-danger/20 transition"
            >
              <Trash2 className="h-4 w-4" />
              <span>Delete My Data</span>
            </button>
          </div>

          {confirmDelete && (
            <div className="rounded-xl border border-danger/30 bg-danger/5 p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-bold text-danger">
                <AlertTriangle className="h-4 w-4" />
                <span>Are you sure you want to delete your entire account and all history?</span>
              </div>
              <p className="text-xs text-danger/80">
                This action is irreversible. All memberships, booking records, intake notes, and AI interaction histories will be permanently destroyed.
              </p>
              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={() => deleteDataMutation.mutate()}
                  disabled={deleteDataMutation.isPending}
                  className="min-h-[44px] rounded-lg bg-danger hover:bg-danger/90 px-4 py-1.5 text-xs font-semibold text-white transition disabled:opacity-50"
                >
                  {deleteDataMutation.isPending ? 'Deleting...' : 'Yes, Delete Everything'}
                </button>
                <button
                  onClick={() => setConfirmDelete(false)}
                  className="min-h-[44px] rounded-lg border border-border px-4 py-1.5 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-raised transition"
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
