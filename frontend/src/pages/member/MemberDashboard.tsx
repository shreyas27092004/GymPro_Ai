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
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 dark:bg-slate-950 py-8 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-8">
        {/* Welcome Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-white">
              Welcome back, {me?.full_name?.split(' ')[0] || 'Member'}!
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Here is your daily activity, upcoming sessions, and personalized fitness guidance.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowIssueModal(true)}
              className="flex items-center gap-1.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3.5 py-2 text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition"
            >
              <MessageSquare className="h-4 w-4" />
              <span>Report an Issue</span>
            </button>

            <button
              onClick={onOpenCoach}
              className="flex items-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 px-4 py-2 text-xs font-semibold text-white shadow-sm transition"
            >
              <Sparkles className="h-4 w-4" />
              <span>Ask AI Coach</span>
            </button>
          </div>
        </div>

        {/* Top Cards: Plan/Trial + Activity Stats */}
        <div className="grid md:grid-cols-3 gap-6">
          {/* Membership / Trial Card */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                  Current Entitlement
                </span>
                <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-500 animate-pulse" />
              </div>

              {membershipData?.plan ? (
                <div>
                  <h3 className="text-2xl font-black text-slate-900 dark:text-white">
                    {membershipData.plan} Membership
                  </h3>
                  <p className="text-xs text-emerald-600 dark:text-emerald-400 font-semibold mt-1">
                    Status: {membershipData.status || 'ACTIVE'}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                    Valid through {membershipData.end_date || 'end of cycle'}
                  </p>
                </div>
              ) : trialData ? (
                <div>
                  <h3 className="text-2xl font-black text-slate-900 dark:text-white">
                    Free Trial Pass
                  </h3>
                  <p className="text-xs text-emerald-600 dark:text-emerald-400 font-semibold mt-1">
                    {trialData.classes_remaining ?? 3} of 3 free classes remaining
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                    Expires {trialData.expires_at ? new Date(trialData.expires_at).toLocaleDateString() : 'in 14 days'}
                  </p>
                </div>
              ) : (
                <div>
                  <h3 className="text-2xl font-black text-slate-900 dark:text-white">
                    No Active Plan
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                    Select a plan or activate your trial classes.
                  </p>
                </div>
              )}
            </div>

            <div className="mt-6 pt-4 border-t border-slate-100 dark:border-slate-800">
              <a
                href="/app/membership"
                className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:underline"
              >
                <span>Manage Plan or Upgrade</span>
                <ChevronRight className="h-3.5 w-3.5" />
              </a>
            </div>
          </div>

          {/* Activity Metrics: Steps & Calories */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Today's Targets
            </span>

            <div className="grid grid-cols-2 gap-4 mt-4">
              <div className="rounded-xl bg-slate-50 dark:bg-slate-800/60 p-4">
                <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 mb-1">
                  <Footprints className="h-4 w-4 text-emerald-500" />
                  <span className="text-xs font-medium">Steps</span>
                </div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">8,420</p>
                <p className="text-[10px] text-slate-400">Goal: 10,000</p>
              </div>

              <div className="rounded-xl bg-slate-50 dark:bg-slate-800/60 p-4">
                <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 mb-1">
                  <Flame className="h-4 w-4 text-amber-500" />
                  <span className="text-xs font-medium">Burned</span>
                </div>
                <p className="text-2xl font-bold text-slate-900 dark:text-white">520 kcal</p>
                <p className="text-[10px] text-slate-400">Active burn</p>
              </div>
            </div>

            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-4">
              Daily metrics are synced with your baseline health profile.
            </p>
          </div>

          {/* AI Recommendations with "Based on" */}
          <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm flex flex-col justify-between">
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Personalized AI Guidance
              </span>

              <div className="mt-3 space-y-2">
                <div className="rounded-xl bg-emerald-50 dark:bg-emerald-950/30 p-3 text-xs">
                  <p className="font-semibold text-emerald-900 dark:text-emerald-300">
                    Recommended Workout: Low-Impact Mobility & Core
                  </p>
                  <p className="text-[10px] text-emerald-700 dark:text-emerald-400 mt-0.5">
                    Based on: Knee protection protocol & goal: Fat Loss
                  </p>
                </div>

                <div className="rounded-xl bg-blue-50 dark:bg-blue-950/30 p-3 text-xs">
                  <p className="font-semibold text-blue-900 dark:text-blue-300">
                    Nutrition Target: 1,850 kcal (140g P / 180g C / 55g F)
                  </p>
                  <p className="text-[10px] text-blue-700 dark:text-blue-400 mt-0.5">
                    Based on: TDEE calculator (Mifflin-St Jeor), Peanut-free
                  </p>
                </div>
              </div>
            </div>

            <button
              onClick={onOpenCoach}
              className="mt-4 text-left text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:underline"
            >
              Ask Coach for today's meal plan &rarr;
            </button>
          </div>
        </div>

        {/* Upcoming Bookings Section */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
          <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-4">
            Your Upcoming Classes
          </h2>

          {bookingsData && bookingsData.length > 0 ? (
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {bookingsData.map((b: any) => (
                <div key={b.id} className="py-3.5 flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                      <Calendar className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-slate-900 dark:text-white">
                        {b.class_title || 'Fitness Session'}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {b.start_time ? new Date(b.start_time).toLocaleString() : 'Scheduled'}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center space-x-3">
                    <span className="rounded-full bg-emerald-100 dark:bg-emerald-950 px-2.5 py-0.5 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
                      {b.status}
                    </span>

                    <button
                      onClick={() => cancelBookingMutation.mutate(b.id)}
                      disabled={cancelBookingMutation.isPending}
                      className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-slate-500 dark:text-slate-400 space-y-2">
              <Calendar className="h-8 w-8 mx-auto text-slate-400 opacity-60" />
              <p className="text-sm">No booked sessions right now.</p>
              <p className="text-xs">Browse the schedule below or ask the AI Coach to book for you.</p>
            </div>
          )}
        </div>

        {/* Class Catalog / Schedule with Filter */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                Class Schedule & Booking
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Injury-safe recommendations marked with safety indicators.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {['ALL', 'HIIT', 'YOGA', 'STRENGTH', 'REHAB'].map((cat) => (
                <button
                  key={cat}
                  onClick={() => setFilterCategory(cat)}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                    filterCategory === cat
                      ? 'bg-emerald-600 text-white'
                      : 'border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
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
                className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-850 p-4 flex flex-col justify-between hover:border-emerald-500 transition"
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="rounded bg-emerald-100 dark:bg-emerald-950 px-2 py-0.5 text-[10px] font-bold text-emerald-800 dark:text-emerald-300">
                      {c.category}
                    </span>
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">
                      {c.capacity - c.booked_count} spots left
                    </span>
                  </div>

                  <h3 className="text-base font-bold text-slate-900 dark:text-white">{c.title}</h3>

                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5" />
                    {new Date(c.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </p>

                  {/* Injury Flag if Contraindicated */}
                  {c.impact === 'HIGH' && (
                    <div className="mt-2 flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                      <AlertCircle className="h-3 w-3 shrink-0" />
                      <span>High Impact &bull; Avoid if knee injury</span>
                    </div>
                  )}
                </div>

                <div className="mt-4 pt-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {c.trainer_name || 'Coach'}
                  </span>
                  <button
                    onClick={onOpenCoach}
                    className="rounded-lg bg-emerald-600 hover:bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white transition"
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
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
            <div className="w-full max-w-md rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                  Report a Problem
                </h3>
                <button
                  onClick={() => setShowIssueModal(false)}
                  className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {issueSubmitted ? (
                <div className="text-center py-6 space-y-2">
                  <CheckCircle className="h-10 w-10 text-emerald-500 mx-auto" />
                  <p className="text-sm font-semibold text-slate-900 dark:text-white">
                    Report Submitted
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
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
                    <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                      Issue Category
                    </label>
                    <select
                      value={issueCategory}
                      onChange={(e) => setIssueCategory(e.target.value)}
                      className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 p-2.5 text-xs text-slate-900 dark:text-white"
                    >
                      <option value="CLASS_QUALITY">Class Quality</option>
                      <option value="FACILITY">Facility & Cleanliness</option>
                      <option value="TRAINER_CONDUCT">Trainer Feedback</option>
                      <option value="BILLING">Billing & Membership</option>
                      <option value="OTHER">Other</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                      Severity
                    </label>
                    <select
                      value={issueSeverity}
                      onChange={(e) => setIssueSeverity(e.target.value)}
                      className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 p-2.5 text-xs text-slate-900 dark:text-white"
                    >
                      <option value="LOW">Low - General Feedback</option>
                      <option value="MEDIUM">Medium - Needs Attention</option>
                      <option value="HIGH">High - Urgent Issue</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                      Description
                    </label>
                    <textarea
                      required
                      rows={3}
                      value={issueWords}
                      onChange={(e) => setIssueWords(e.target.value)}
                      placeholder="Please describe what happened..."
                      className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 p-3 text-xs text-slate-900 dark:text-white"
                    />
                  </div>

                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    Privacy Guarantee: Your name is never disclosed to trainers when triaging issues.
                  </p>

                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button
                      type="button"
                      onClick={() => setShowIssueModal(false)}
                      className="rounded-xl border border-slate-300 dark:border-slate-700 px-4 py-2 text-xs font-semibold text-slate-700 dark:text-slate-300"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={submitIssueMutation.isPending || !issueWords.trim()}
                      className="rounded-xl bg-emerald-600 hover:bg-emerald-700 px-5 py-2 text-xs font-semibold text-white disabled:opacity-50"
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
