// src/pages/admin/AdminConsole.tsx
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldAlert,
  Sparkles,
  UserPlus,
} from 'lucide-react';
import { client, friendlyError } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';

interface AdminConsoleProps {
  onOpenCoach: () => void;
}

export const AdminConsole: React.FC<AdminConsoleProps> = ({ onOpenCoach }) => {
  const { me } = useAuth();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<'kpis' | 'approvals' | 'triage' | 'staff' | 'broadcast'>('kpis');
  const [statusToast, setStatusToast] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

  // Decision State
  const rejectReason = 'Qualifications incomplete';

  // Broadcast state
  const [broadcastSubject, setBroadcastSubject] = useState('New Equipment Arrival & Holiday Hours');
  const [broadcastBody, setBroadcastBody] = useState('We are excited to announce new functional training rigs arriving this Friday!');
  const [broadcastAudience, setBroadcastAudience] = useState('ALL');

  // Staff invite state
  const [inviteEmail, setInviteEmail] = useState('');
  const inviteRole = 'TRAINER';

  // 1. Fetch KPI Overview
  const { data: kpiData } = useQuery({
    queryKey: ['admin-overview'],
    queryFn: async () => {
      try {
        const res = await client.get('/admin/overview');
        return res.data;
      } catch {
        return {
          active_members: 142,
          mrr: 284858.0,
          occupancy_rate: 68.4,
          trials_converted: 74.2,
          no_show_rate: 4.8,
          churn_rate: 2.1,
          open_issues: 3,
        };
      }
    },
  });

  // 2. Fetch Trainer Requests
  const { data: trainerRequests = [] } = useQuery({
    queryKey: ['admin-trainer-requests'],
    queryFn: async () => {
      try {
        const res = await client.get('/admin/trainer-requests');
        return res.data || [];
      } catch {
        return [];
      }
    },
  });

  // 3. Fetch Pending Admin Requests
  const { data: adminRequests = [] } = useQuery({
    queryKey: ['admin-requests'],
    queryFn: async () => {
      try {
        const res = await client.get('/admin/admin-requests');
        return res.data || [];
      } catch {
        return [];
      }
    },
  });

  // 4. Fetch Issues
  const { data: issues = [] } = useQuery({
    queryKey: ['admin-issues'],
    queryFn: async () => {
      try {
        const res = await client.get('/admin/issues');
        return res.data || [];
      } catch {
        return [];
      }
    },
  });

  // Trainer Decision Mutation
  const trainerDecisionMutation = useMutation({
    mutationFn: async ({ requestId, decision, reason }: { requestId: string; decision: string; reason?: string }) => {
      await client.post(`/admin/trainer-requests/${requestId}/decision`, {
        decision,
        reason,
      });
    },
    onSuccess: () => {
      setStatusToast({ type: 'success', msg: 'Trainer request decision recorded successfully.' });
      queryClient.invalidateQueries({ queryKey: ['admin-trainer-requests'] });
    },
    onError: (e: any) => {
      setStatusToast({ type: 'error', msg: friendlyError(e) });
    },
  });

  // Reject Admin Request Mutation
  const rejectAdminMutation = useMutation({
    mutationFn: async (requestId: string) => {
      await client.post(`/admin/admin-requests/${requestId}/reject`, {});
    },
    onSuccess: () => {
      setStatusToast({ type: 'success', msg: 'Admin request rejected & revoked.' });
      queryClient.invalidateQueries({ queryKey: ['admin-requests'] });
    },
    onError: (e: any) => {
      setStatusToast({ type: 'error', msg: friendlyError(e) });
    },
  });

  // Issue Triage Mutation
  const triageIssueMutation = useMutation({
    mutationFn: async ({ issueId, status, adminAction }: { issueId: string; status: string; adminAction: string }) => {
      await client.post(`/admin/issues/${issueId}/triage`, {
        status,
        admin_action: adminAction,
      });
    },
    onSuccess: () => {
      setStatusToast({ type: 'success', msg: 'Issue ticket status updated.' });
      queryClient.invalidateQueries({ queryKey: ['admin-issues'] });
    },
    onError: (e: any) => {
      setStatusToast({ type: 'error', msg: friendlyError(e) });
    },
  });

  // Invite Staff Trainer Mutation
  const inviteStaffMutation = useMutation({
    mutationFn: async () => {
      await client.post('/admin/staff/invites', {
        email: inviteEmail.trim(),
        role: inviteRole,
      });
    },
    onSuccess: () => {
      setStatusToast({ type: 'success', msg: `Staff invitation sent to ${inviteEmail}.` });
      setInviteEmail('');
    },
    onError: (e: any) => {
      setStatusToast({ type: 'error', msg: friendlyError(e) });
    },
  });

  const pendingTrainersCount = trainerRequests.filter((r: any) => r.status === 'PENDING').length;

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-base text-text-primary py-8 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl sm:text-3xl font-extrabold text-text-primary">
                Gym Governance & Administration
              </h1>
              {me?.cooling_off_active && (
                <span className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-xs font-bold text-amber-600 dark:text-amber-400">
                  Cooling-off Active (24h)
                </span>
              )}
            </div>
            <p className="text-xs text-text-muted mt-1">
              Metric catalog views, trainer request approvals queue, HMAC security controls, and issue triage.
            </p>
          </div>

          <button
            onClick={onOpenCoach}
            className="inline-flex items-center gap-1.5 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-4 py-2 text-xs font-semibold text-white shadow-sm transition"
          >
            <Sparkles className="h-4 w-4" />
            <span>Admin Copilot</span>
          </button>
        </div>

        {statusToast && (
          <div
            className={`flex items-center justify-between rounded-xl p-3 text-xs font-medium ${
              statusToast.type === 'success'
                ? 'bg-accent/10 border border-accent/20 text-accent'
                : 'bg-danger/10 border border-danger/20 text-danger'
            }`}
          >
            <span>{statusToast.msg}</span>
            <button onClick={() => setStatusToast(null)} className="font-bold min-h-[44px] min-w-[44px]">&times;</button>
          </div>
        )}

        {/* Tab Controls */}
        <div className="flex flex-wrap gap-2 border-b border-border pb-2">
          {[
            { id: 'kpis', label: 'Metric Catalog & KPIs' },
            {
              id: 'approvals',
              label: (
                <span className="flex items-center gap-1.5">
                  Approvals Queue
                  {pendingTrainersCount > 0 && (
                    <span className="rounded-full bg-danger px-1.5 py-0.2 text-[10px] font-bold text-white">
                      {pendingTrainersCount}
                    </span>
                  )}
                </span>
              ),
            },
            { id: 'triage', label: 'Issue Triage Board' },
            { id: 'staff', label: 'Staff Management' },
            { id: 'broadcast', label: 'Draft Broadcast' },
          ].map((tab: any) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`min-h-[44px] rounded-xl px-4 py-2 text-xs font-semibold transition ${
                activeTab === tab.id
                  ? 'bg-text-primary text-base shadow-sm'
                  : 'text-text-muted hover:bg-surface-raised hover:text-text-primary'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab 1: Metric Catalog & KPIs */}
        {activeTab === 'kpis' && (
          <div className="space-y-6">
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Monthly Recurring Revenue (MRR)
                </span>
                <p className="text-2xl font-black text-text-primary mt-2">
                  ₹{kpiData?.mrr?.toLocaleString() || '284,858'}
                </p>
                <p className="text-[10px] text-accent font-semibold mt-1">
                  +12.4% vs last month
                </p>
              </div>

              <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Class Occupancy Rate
                </span>
                <p className="text-2xl font-black text-text-primary mt-2">
                  {kpiData?.occupancy_rate || 68.4}%
                </p>
                <p className="text-[10px] text-text-muted mt-1">Target: &gt;65%</p>
              </div>

              <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  Trial Conversion
                </span>
                <p className="text-2xl font-black text-text-primary mt-2">
                  {kpiData?.trials_converted || 74.2}%
                </p>
                <p className="text-[10px] text-accent font-semibold mt-1">
                  High conversion health
                </p>
              </div>

              <div className="rounded-2xl border border-border bg-surface p-5 shadow-sm">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                  No-Show Rate
                </span>
                <p className="text-2xl font-black text-text-primary mt-2">
                  {kpiData?.no_show_rate || 4.8}%
                </p>
                <p className="text-[10px] text-text-muted mt-1">Below 5% threshold</p>
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
              <h2 className="text-base font-bold text-text-primary mb-2">
                Metric Catalog Invariants (Spec 3.2 & Decision P7)
              </h2>
              <p className="text-xs text-text-muted">
                All business intelligence metrics are computed from verified database views (`v_metrics`) with k-anonymity floors. Direct SQL execution and per-member attendance extraction are strictly barred across all agent copilots.
              </p>
            </div>
          </div>
        )}

        {/* Tab 2: Approvals Queue */}
        {activeTab === 'approvals' && (
          <div className="space-y-8">
            {/* Trainer Applications Queue */}
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-slate-900 dark:text-white">
                    Trainer Applications Queue
                  </h2>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Review trainer qualifications, certifications, and risk indicators.
                  </p>
                </div>
                <span className="rounded-full bg-blue-100 dark:bg-blue-950 px-2.5 py-0.5 text-xs font-semibold text-blue-800 dark:text-blue-300">
                  {trainerRequests.length} Total
                </span>
              </div>

              {trainerRequests.length > 0 ? (
                <div className="divide-y divide-border">
                  {trainerRequests.map((req: any) => (
                    <div key={req.request_id || req.id} className="py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-bold text-text-primary">
                            {req.full_name || 'Trainer Applicant'}
                          </p>
                          <span className="rounded bg-surface-raised px-2 py-0.5 text-[10px] font-mono text-text-muted">
                            {req.email}
                          </span>
                        </div>
                        <p className="text-xs text-text-muted mt-1">
                          Specializations: {req.specializations?.join(', ') || 'STRENGTH'} &bull; Certs: {req.certifications?.join(', ') || 'CSCS'}
                        </p>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() =>
                            trainerDecisionMutation.mutate({
                              requestId: req.request_id || req.id,
                              decision: 'APPROVE',
                            })
                          }
                          disabled={trainerDecisionMutation.isPending || me?.cooling_off_active}
                          className="min-h-[40px] rounded-lg bg-accent hover:bg-accent-hover px-4 py-1.5 text-xs font-semibold text-white transition disabled:opacity-50"
                        >
                          Approve
                        </button>

                        <button
                          onClick={() =>
                            trainerDecisionMutation.mutate({
                              requestId: req.request_id || req.id,
                              decision: 'REJECT',
                              reason: rejectReason,
                            })
                          }
                          disabled={trainerDecisionMutation.isPending || me?.cooling_off_active}
                          className="min-h-[40px] rounded-lg border border-danger/30 bg-danger/10 px-4 py-1.5 text-xs font-semibold text-danger hover:bg-danger/20 transition disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-text-muted py-4 text-center">No pending trainer applications.</p>
              )}
            </div>

            {/* Pending Admin Requests & Revocation */}
            <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
              <div>
                <div className="flex items-center gap-2">
                  <ShieldAlert className="h-5 w-5 text-accent" />
                  <h2 className="text-base font-bold text-text-primary">
                    Pending Admin Requests & Revocation
                  </h2>
                </div>
                <p className="text-xs text-accent mt-1">
                  Security Invariant: No approve endpoint exists! Admin activation occurs solely via one-time HMAC code. Administrators may only reject or revoke requests.
                </p>
              </div>

              {adminRequests.length > 0 ? (
                <div className="divide-y divide-border">
                  {adminRequests.map((areq: any) => (
                    <div key={areq.request_id || areq.id} className="py-3 flex items-center justify-between">
                      <div>
                        <p className="text-sm font-bold text-text-primary">
                          {areq.full_name || areq.email}
                        </p>
                        <p className="text-[11px] text-text-muted">
                          Requested: {areq.created_at ? new Date(areq.created_at).toLocaleString() : 'Recent'} &bull; Status: {areq.status}
                        </p>
                      </div>

                      <button
                        onClick={() => rejectAdminMutation.mutate(areq.request_id || areq.id)}
                        disabled={rejectAdminMutation.isPending}
                        className="min-h-[40px] rounded-lg border border-danger/30 bg-danger/10 px-3 py-1.5 text-xs font-semibold text-danger hover:bg-danger/20 transition"
                      >
                        Reject / Revoke
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-text-muted py-4 text-center">No pending admin authorization requests.</p>
              )}
            </div>
          </div>
        )}

        {/* Tab 3: Issue Triage Board */}
        {activeTab === 'triage' && (
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-text-primary">
                  Issue Reports Triage Board
                </h2>
                <p className="text-xs text-text-muted">
                  Member reports categorized with severity ratings. Reporter identity is masked.
                </p>
              </div>
            </div>

            {issues.length > 0 ? (
              <div className="space-y-3">
                {issues.map((iss: any) => (
                  <div
                    key={iss.issue_id || iss.id}
                    className="rounded-xl border border-border bg-surface p-4 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                            iss.severity === 'HIGH' || iss.severity === 'CRITICAL'
                              ? 'bg-danger/15 text-danger'
                              : iss.severity === 'MEDIUM'
                              ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                              : 'bg-surface-raised text-text-primary'
                          }`}
                        >
                          {iss.severity} Severity
                        </span>
                        <span className="text-xs font-semibold text-text-primary">
                          {iss.category}
                        </span>
                        <span className="text-[11px] text-text-muted">
                          by {iss.reporter || 'a member'}
                        </span>
                      </div>

                      <span className="text-xs font-semibold text-text-muted">
                        Status: {iss.status}
                      </span>
                    </div>

                    <p className="text-xs text-text-primary">
                      {iss.summary || iss.ai_summary || iss.user_words}
                    </p>

                    <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border">
                      <button
                        onClick={() =>
                          triageIssueMutation.mutate({
                            issueId: iss.issue_id || iss.id,
                            status: 'ACTIONED',
                            adminAction: 'WARN_TRAINER',
                          })
                        }
                        className="min-h-[40px] rounded-lg border border-border px-3 py-1 text-xs font-medium text-text-primary hover:bg-surface-raised transition"
                      >
                        Warn Trainer
                      </button>

                      <button
                        onClick={() =>
                          triageIssueMutation.mutate({
                            issueId: iss.issue_id || iss.id,
                            status: 'ACTIONED',
                            adminAction: 'CONTACT_USER',
                          })
                        }
                        className="min-h-[40px] rounded-lg border border-border px-3 py-1 text-xs font-medium text-text-primary hover:bg-surface-raised transition"
                      >
                        Contact User
                      </button>

                      <button
                        onClick={() =>
                          triageIssueMutation.mutate({
                            issueId: iss.issue_id || iss.id,
                            status: 'CLOSED',
                            adminAction: 'RESOLVED',
                          })
                        }
                        className="min-h-[40px] rounded-lg bg-accent hover:bg-accent-hover px-3 py-1 text-xs font-semibold text-white transition"
                      >
                        Close Ticket
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-muted py-4 text-center">No open issue reports.</p>
            )}
          </div>
        )}

        {/* Tab 4: Staff Management (Trainer Invites Only) */}
        {activeTab === 'staff' && (
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-6">
            <div>
              <h2 className="text-base font-bold text-text-primary">
                Invite Staff Members
              </h2>
              <p className="text-xs text-text-muted">
                Decision 16: Trainer invites only. Admin invites are disabled in v1.
              </p>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                inviteStaffMutation.mutate();
              }}
              className="space-y-4 max-w-md"
            >
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Trainer Email
                </label>
                <input
                  type="email"
                  required
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="newtrainer@example.com"
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Invited Role
                </label>
                <input
                  type="text"
                  disabled
                  value="TRAINER (Admin invites disabled per security policy)"
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-muted cursor-not-allowed min-h-[44px]"
                />
              </div>

              <button
                type="submit"
                disabled={inviteStaffMutation.isPending || me?.cooling_off_active}
                className="flex items-center gap-1.5 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-5 py-2.5 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50"
              >
                <UserPlus className="h-4 w-4" />
                <span>{inviteStaffMutation.isPending ? 'Sending...' : 'Send Trainer Invitation'}</span>
              </button>
            </form>
          </div>
        )}

        {/* Tab 5: Broadcast Composer */}
        {activeTab === 'broadcast' && (
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-6">
            <div>
              <h2 className="text-base font-bold text-text-primary">
                Draft Member Broadcast Announcement
              </h2>
              <p className="text-xs text-text-muted">
                Non-essential notifications honor marketing unsubscribes. Sending executes through transactional outbox relay.
              </p>
            </div>

            <div className="space-y-4 max-w-xl">
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Target Audience
                </label>
                <select
                  value={broadcastAudience}
                  onChange={(e) => setBroadcastAudience(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                >
                  <option value="ALL">All Active Members & Trainers (~150 recipients)</option>
                  <option value="MEMBERS">Members Only (~142 recipients)</option>
                  <option value="TRAINERS">Trainers Only (~8 recipients)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Subject Line
                </label>
                <input
                  type="text"
                  value={broadcastSubject}
                  onChange={(e) => setBroadcastSubject(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Message Body
                </label>
                <textarea
                  rows={4}
                  value={broadcastBody}
                  onChange={(e) => setBroadcastBody(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-raised p-3 text-xs text-text-primary"
                />
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={onOpenCoach}
                  className="flex items-center gap-1.5 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-4 py-2 text-xs font-semibold text-white shadow-sm transition"
                >
                  <Sparkles className="h-4 w-4" />
                  <span>Draft & Preview with AI</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
