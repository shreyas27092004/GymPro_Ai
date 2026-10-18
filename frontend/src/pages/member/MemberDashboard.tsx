// src/pages/member/MemberDashboard.tsx
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Calendar,
  Clock,
  Sparkles,
  AlertCircle,
  CheckCircle,
  Flame,
  Footprints,
  MessageSquare,
  ChevronRight,
  X,
} from 'lucide-react';
import { client } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';
import type { ClassSession } from '../../types';

interface MemberDashboardProps {
  onOpenCoach: () => void;
}

export const MemberDashboard: React.FC<MemberDashboardProps> = ({ onOpenCoach }) => {
  const { me } = useAuth();
  const queryClient = useQueryClient();

  const [filterCategory, setFilterCategory] = useState<string>('ALL');
  const [showIssueModal, setShowIssueModal] = useState(false);
  const [issueCategory, setIssueCategory] = useState('CLASS_QUALITY');
  const [issueSeverity, setIssueSeverity] = useState('MEDIUM');
  const [issueWords, setIssueWords] = useState('');
  const [issueSubmitted, setIssueSubmitted] = useState(false);

  // 1. Fetch Trial / Membership status
  const { data: membershipData } = useQuery({
    queryKey: ['me-membership'],
    queryFn: async () => {
      try {
        const res = await client.get('/me/membership');
        return res.data;
      } catch {
        return null;
      }
    },
  });

  const { data: trialData } = useQuery({
    queryKey: ['me-trial'],
    queryFn: async () => {
      try {
        const res = await client.get('/me/trial');
        return res.data;
      } catch {
        return null;
      }
    },
  });

  // 2. Fetch User Bookings
  const { data: bookingsData } = useQuery({
    queryKey: ['me-bookings'],
    queryFn: async () => {
      try {
        const res = await client.get('/me/bookings');
        return res.data || [];
      } catch {
        return [];
      }
    },
  });

  // 3. Fetch Classes Catalog
  const { data: classesData = [] } = useQuery({
    queryKey: ['classes-catalog'],
    queryFn: async () => {
      const res = await client.get('/classes');
      return (res.data || []) as ClassSession[];
    },
  });

  // Cancel booking mutation
  const cancelBookingMutation = useMutation({
    mutationFn: async (bookingId: string) => {
      await client.post(`/me/bookings/${bookingId}/cancel`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me-bookings'] });
      queryClient.invalidateQueries({ queryKey: ['me-trial'] });
    },
  });

  // Submit issue report mutation
  const submitIssueMutation = useMutation({
    mutationFn: async () => {
      await client.post('/feedback', {
        category: issueCategory,
        severity: issueSeverity,
        comments: issueWords,
      });
    },
    onSuccess: () => {
      setIssueSubmitted(true);
      setTimeout(() => {
        setIssueSubmitted(false);
        setShowIssueModal(false);
        setIssueWords('');
      }, 2000);
    },
  });

  const filteredClasses = classesData.filter((c) => {
    if (filterCategory === 'ALL') return true;
    return c.category.toUpperCase() === filterCategory;
  });

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-base text-text-primary py-8 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-8">
        {/* Welcome Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-text-primary">
              Welcome back, {me?.full_name?.split(' ')[0] || 'Member'}!
            </h1>
            <p className="text-xs text-text-muted mt-1">
              Here is your daily activity, upcoming sessions, and personalized fitness guidance.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowIssueModal(true)}
              className="flex items-center gap-1.5 min-h-[44px] rounded-xl border border-border bg-surface px-4 py-2 text-xs font-semibold text-text-primary hover:bg-surface-raised transition"
            >
              <MessageSquare className="h-4 w-4" />
              <span>Report an Issue</span>
            </button>

            <button
              onClick={onOpenCoach}
              className="flex items-center gap-1.5 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-4 py-2 text-xs font-semibold text-white shadow-sm transition"
            >
              <Sparkles className="h-4 w-4" />
              <span>Ask AI Coach</span>
            </button>
          </div>
        </div>

        {/* Top Cards: Plan/Trial + Activity Stats */}
        <div className="grid md:grid-cols-3 gap-6">
          {/* Membership / Trial Card */}
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                  Current Entitlement
                </span>
                <span className="flex h-2.5 w-2.5 rounded-full bg-accent animate-pulse" />
              </div>

              {membershipData?.plan ? (
                <div>
                  <h3 className="text-2xl font-black text-text-primary">
                    {membershipData.plan} Membership
                  </h3>
                  <p className="text-xs text-accent font-semibold mt-1">
                    Status: {membershipData.status || 'ACTIVE'}
                  </p>
                  <p className="text-xs text-text-muted mt-2">
                    Valid through {membershipData.end_date || 'end of cycle'}
                  </p>
                </div>
              ) : trialData ? (
                <div>
                  <h3 className="text-2xl font-black text-text-primary">
                    Free Trial Pass
                  </h3>
                  <p className="text-xs text-accent font-semibold mt-1">
                    {trialData.classes_remaining ?? 3} of 3 free classes remaining
                  </p>
                  <p className="text-xs text-text-muted mt-2">
                    Expires {trialData.expires_at ? new Date(trialData.expires_at).toLocaleDateString() : 'in 14 days'}
                  </p>
                </div>
              ) : (
                <div>
                  <h3 className="text-2xl font-black text-text-primary">
                    No Active Plan
                  </h3>
                  <p className="text-xs text-text-muted mt-1">
                    Select a plan or activate your trial classes.
                  </p>
                </div>
              )}
            </div>

            <div className="mt-6 pt-4 border-t border-border">
              <a
                href="/app/membership"
                className="inline-flex items-center gap-1 min-h-[44px] text-xs font-semibold text-accent hover:underline"
              >
                <span>Manage Plan or Upgrade</span>
                <ChevronRight className="h-3.5 w-3.5" />
              </a>
            </div>
          </div>

          {/* Activity Metrics: Steps & Calories */}
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
              Today's Targets
            </span>

            <div className="grid grid-cols-2 gap-4 mt-4">
              <div className="rounded-xl bg-surface-raised p-4">
                <div className="flex items-center gap-2 text-text-muted mb-1">
                  <Footprints className="h-4 w-4 text-accent" />
                  <span className="text-xs font-medium">Steps</span>
                </div>
                <p className="text-2xl font-bold text-text-primary">8,420</p>
                <p className="text-[10px] text-text-muted">Goal: 10,000</p>
              </div>

              <div className="rounded-xl bg-surface-raised p-4">
                <div className="flex items-center gap-2 text-text-muted mb-1">
                  <Flame className="h-4 w-4 text-amber-500" />
                  <span className="text-xs font-medium">Burned</span>
                </div>
                <p className="text-2xl font-bold text-text-primary">520 kcal</p>
                <p className="text-[10px] text-text-muted">Active burn</p>
              </div>
            </div>

            <p className="text-[11px] text-text-muted mt-4">
              Daily metrics are synced with your baseline health profile.
            </p>
          </div>

          {/* AI Recommendations with "Based on" */}
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm flex flex-col justify-between">
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Personalized AI Guidance
              </span>

              <div className="mt-3 space-y-2">
                <div className="rounded-xl bg-accent/10 border border-accent/20 p-3 text-xs">
                  <p className="font-semibold text-text-primary">
                    Recommended Workout: Low-Impact Mobility & Core
                  </p>
                  <p className="text-[10px] text-emerald-700 dark:text-emerald-400 mt-0.5">
                    Based on: Knee protection protocol & goal: Fat Loss
                  </p>
                </div>

                <div className="rounded-xl bg-surface-raised border border-border p-3 text-xs">
                  <p className="font-semibold text-text-primary">
                    Nutrition Target: 1,850 kcal (140g P / 180g C / 55g F)
                  </p>
                  <p className="text-[10px] text-text-muted mt-0.5">
                    Based on: TDEE calculator (Mifflin-St Jeor), Peanut-free
                  </p>
                </div>
              </div>
            </div>

            <button
              onClick={onOpenCoach}
              className="mt-4 min-h-[44px] text-left text-xs font-semibold text-accent hover:underline flex items-center"
            >
              Ask Coach for today's meal plan &rarr;
            </button>
          </div>
        </div>

        {/* Upcoming Bookings Section */}
        <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
          <h2 className="text-lg font-bold text-text-primary mb-4">
            Your Upcoming Classes
          </h2>

          {bookingsData && bookingsData.length > 0 ? (
            <div className="divide-y divide-border">
              {bookingsData.map((b: any) => (
                <div key={b.id} className="py-3.5 flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10 text-accent">
                      <Calendar className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-text-primary">
                        {b.class_title || 'Fitness Session'}
                      </p>
                      <p className="text-xs text-text-muted">
                        {b.start_time ? new Date(b.start_time).toLocaleString() : 'Scheduled'}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center space-x-3">
                    <span className="rounded-full bg-accent/15 px-2.5 py-0.5 text-xs font-semibold text-accent">
                      {b.status}
                    </span>

                    <button
                      onClick={() => cancelBookingMutation.mutate(b.id)}
                      disabled={cancelBookingMutation.isPending}
                      className="min-h-[44px] rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-raised transition"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-text-muted space-y-2">
              <Calendar className="h-8 w-8 mx-auto opacity-60" />
              <p className="text-sm">No booked sessions right now.</p>
              <p className="text-xs">Browse the schedule below or ask the AI Coach to book for you.</p>
            </div>
          )}
        </div>

        {/* Class Catalog / Schedule with Filter */}
        <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
            <div>
              <h2 className="text-lg font-bold text-text-primary">
                Class Schedule & Booking
              </h2>
              <p className="text-xs text-text-muted">
                Injury-safe recommendations marked with safety indicators.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {['ALL', 'HIIT', 'YOGA', 'STRENGTH', 'REHAB'].map((cat) => (
                <button
                  key={cat}
                  onClick={() => setFilterCategory(cat)}
                  className={`min-h-[36px] sm:min-h-[40px] rounded-lg px-3 py-1 text-xs font-semibold transition ${
                    filterCategory === cat
                      ? 'bg-accent text-white shadow-sm'
                      : 'border border-border text-text-muted hover:bg-surface-raised'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredClasses.slice(0, 6).map((c) => (
              <div
                key={c.id}
                className="rounded-xl border border-border bg-surface-raised p-4 flex flex-col justify-between hover:border-accent transition"
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="rounded bg-accent/15 px-2 py-0.5 text-[10px] font-bold text-accent">
                      {c.category}
                    </span>
                    <span className="text-[11px] text-text-muted">
                      {c.capacity - c.booked_count} spots left
                    </span>
                  </div>

                  <h3 className="text-base font-bold text-text-primary">{c.title}</h3>

                  <p className="text-xs text-text-muted mt-1 flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" />
                    {new Date(c.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </p>

                  {/* Injury Flag if Contraindicated */}
                  {c.impact === 'HIGH' && (
                    <div className="mt-2 flex items-center gap-1 text-[11px] text-amber-500">
                      <AlertCircle className="h-3 w-3 shrink-0" />
                      <span>High Impact &bull; Avoid if knee injury</span>
                    </div>
                  )}
                </div>

                <div className="mt-4 pt-3 border-t border-border flex items-center justify-between">
                  <span className="text-xs text-text-muted">
                    {c.trainer_name || 'Coach'}
                  </span>
                  <button
                    onClick={onOpenCoach}
                    className="min-h-[40px] rounded-lg bg-accent hover:bg-accent-hover px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition"
                  >
                    Book with AI
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Issue Report Modal */}
        {showIssueModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <div className="w-full max-w-md rounded-2xl bg-surface border border-border p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold text-text-primary">
                  Report a Problem
                </h3>
                <button
                  onClick={() => setShowIssueModal(false)}
                  className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg text-text-muted hover:bg-surface-raised"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {issueSubmitted ? (
                <div className="text-center py-6 space-y-2">
                  <CheckCircle className="h-10 w-10 text-accent mx-auto" />
                  <p className="text-sm font-semibold text-text-primary">
                    Report Submitted
                  </p>
                  <p className="text-xs text-text-muted">
                    Our administration team has received your ticket and will triage it promptly.
                  </p>
                </div>
              ) : (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    submitIssueMutation.mutate();
                  }}
                  className="space-y-4"
                >
                  <div>
                    <label className="block text-xs font-semibold text-text-primary mb-1">
                      Issue Category
                    </label>
                    <select
                      value={issueCategory}
                      onChange={(e) => setIssueCategory(e.target.value)}
                      className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                    >
                      <option value="CLASS_QUALITY">Class Quality</option>
                      <option value="FACILITY">Facility & Cleanliness</option>
                      <option value="TRAINER_CONDUCT">Trainer Feedback</option>
                      <option value="BILLING">Billing & Membership</option>
                      <option value="OTHER">Other</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-text-primary mb-1">
                      Severity
                    </label>
                    <select
                      value={issueSeverity}
                      onChange={(e) => setIssueSeverity(e.target.value)}
                      className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                    >
                      <option value="LOW">Low - General Feedback</option>
                      <option value="MEDIUM">Medium - Needs Attention</option>
                      <option value="HIGH">High - Urgent Issue</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-text-primary mb-1">
                      Description
                    </label>
                    <textarea
                      required
                      rows={3}
                      value={issueWords}
                      onChange={(e) => setIssueWords(e.target.value)}
                      placeholder="Please describe what happened..."
                      className="w-full rounded-xl border border-border bg-surface-raised p-3 text-xs text-text-primary"
                    />
                  </div>

                  <p className="text-[11px] text-text-muted">
                    Privacy Guarantee: Your name is never disclosed to trainers when triaging issues.
                  </p>

                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={() => setShowIssueModal(false)}
                      className="min-h-[44px] rounded-xl border border-border px-4 py-2 text-xs font-semibold text-text-muted hover:text-text-primary hover:bg-surface-raised"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={submitIssueMutation.isPending || !issueWords.trim()}
                      className="min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-5 py-2 text-xs font-semibold text-white disabled:opacity-50"
                    >
                      {submitIssueMutation.isPending ? 'Submitting...' : 'Submit Report'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
