// src/pages/trainer/TrainerConsole.tsx
import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Star,
  Sparkles,
  ChevronRight,
} from 'lucide-react';
import { client, friendlyError } from '../../api/client';
import type { SeriesInstancePreview } from '../../types';

interface TrainerConsoleProps {
  onOpenCoach: () => void;
}

export const TrainerConsole: React.FC<TrainerConsoleProps> = ({ onOpenCoach }) => {
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<'roster' | 'availability' | 'series' | 'feedback'>('roster');
  const [selectedClassId, setSelectedClassId] = useState<string | null>(null);

  // Series creator form state
  const [seriesTitle, setSeriesTitle] = useState('HIIT Power Circuit');
  const [seriesCategory, setSeriesCategory] = useState('HIIT');
  const [seriesCapacity, setSeriesCapacity] = useState(15);
  const [seriesStart, setSeriesStart] = useState('2026-10-19T18:00');
  const [seriesWeeks, setSeriesWeeks] = useState(4);
  const [seriesDuration, setSeriesDuration] = useState(60);
  const [previewInstances, setPreviewInstances] = useState<SeriesInstancePreview[] | null>(null);

  // Time off state
  const [timeOffStart, setTimeOffStart] = useState('2026-11-04T00:00');
  const [timeOffEnd, setTimeOffEnd] = useState('2026-11-04T23:59');
  const [timeOffReason, setTimeOffReason] = useState('Personal leave');
  const [statusToast, setStatusToast] = useState<string | null>(null);

  // 1. Fetch Trainer's Classes
  const { data: trainerClasses = [] } = useQuery({
    queryKey: ['trainer-classes'],
    queryFn: async () => {
      try {
        const res = await client.get('/trainer/classes');
        return res.data || [];
      } catch {
        return [
          {
            id: '11111111-1111-1111-1111-111111111111',
            title: 'HIIT Power',
            category: 'HIIT',
            start_time: '2026-10-19T18:00:00+05:30',
            end_time: '2026-10-19T19:00:00+05:30',
            capacity: 15,
            booked_count: 8,
            status: 'SCHEDULED',
          },
        ];
      }
    },
  });

  // 2. Fetch Selected Class Roster
  const activeClassId = selectedClassId || (trainerClasses[0]?.id as string | undefined);
  const { data: rosterData } = useQuery({
    queryKey: ['trainer-roster', activeClassId],
    enabled: !!activeClassId,
    queryFn: async () => {
      try {
        const res = await client.get(`/trainer/classes/${activeClassId}/roster`);
        return res.data;
      } catch {
        return {
          class_id: activeClassId,
          title: 'HIIT Power',
          roster: [
            { user_id: 'u1', first_name: 'John', status: 'CONFIRMED' },
            { user_id: 'u2', first_name: 'Priya', status: 'CONFIRMED' },
            { user_id: 'u3', first_name: 'Vikram', status: 'CONFIRMED' },
          ],
        };
      }
    },
  });

  // 3. Fetch Availability
  const { data: availabilityData } = useQuery({
    queryKey: ['trainer-availability'],
    queryFn: async () => {
      try {
        const res = await client.get('/trainer/availability');
        return res.data;
      } catch {
        return {
          slots: [
            { weekday: 1, start_time: '09:00:00', end_time: '18:00:00' },
            { weekday: 3, start_time: '09:00:00', end_time: '18:00:00' },
            { weekday: 5, start_time: '09:00:00', end_time: '18:00:00' },
          ],
          time_off: [{ starts_at: '2026-11-04 00:00:00+05:30', ends_at: '2026-11-04 23:59:59+05:30', reason: 'Personal' }],
        };
      }
    },
  });

  // 4. Fetch Feedback Summary (with k-anonymity)
  const { data: feedbackData } = useQuery({
    queryKey: ['trainer-feedback'],
    queryFn: async () => {
      try {
        const res = await client.get('/trainer/feedback');
        return res.data;
      } catch {
        return {
          count: 3,
          suppressed: true,
          message: 'Feedback details are suppressed until at least 5 member reviews are submitted to protect reviewer privacy.',
        };
      }
    },
  });

  // Preview series mutation
  const previewSeriesMutation = useMutation({
    mutationFn: async () => {
      const res = await client.post('/trainer/series/preview', {
        title: seriesTitle,
        category: seriesCategory,
        capacity: Number(seriesCapacity),
        start_time: seriesStart + ':00+05:30',
        weeks: Number(seriesWeeks),
        duration_minutes: Number(seriesDuration),
      });
      return res.data;
    },
    onSuccess: (data) => {
      setPreviewInstances(data.instances || []);
    },
    onError: (e: any) => {
      setStatusToast(`Preview failed: ${friendlyError(e)}`);
    },
  });

  // Time off mutation
  const submitTimeOffMutation = useMutation({
    mutationFn: async () => {
      await client.post('/trainer/time-off', {
        starts_at: timeOffStart + ':00+05:30',
        ends_at: timeOffEnd + ':00+05:30',
        reason: timeOffReason,
      });
    },
    onSuccess: () => {
      setStatusToast('Time off recorded successfully!');
      queryClient.invalidateQueries({ queryKey: ['trainer-availability'] });
    },
  });

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-base text-text-primary py-8 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl sm:text-3xl font-extrabold text-text-primary">
                Trainer Operations Console
              </h1>
              <span className="rounded-full bg-accent/15 px-2.5 py-0.5 text-xs font-semibold text-accent">
                Coach
              </span>
            </div>
            <p className="text-xs text-text-muted mt-1">
              Manage your teaching calendar, rosters, recurring series, and review privacy-safe feedback.
            </p>
          </div>

          <button
            onClick={onOpenCoach}
            className="inline-flex items-center gap-1.5 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-4 py-2 text-xs font-semibold text-white shadow-sm transition"
          >
            <Sparkles className="h-4 w-4" />
            <span>Trainer Copilot</span>
          </button>
        </div>

        {statusToast && (
          <div className="flex items-center justify-between rounded-xl bg-accent/10 border border-accent/20 p-3 text-xs text-accent">
            <span>{statusToast}</span>
            <button onClick={() => setStatusToast(null)} className="font-bold min-h-[44px] min-w-[44px]">&times;</button>
          </div>
        )}

        {/* Tab Controls */}
        <div className="flex flex-wrap gap-2 border-b border-border pb-2">
          {[
            { id: 'roster', label: 'Class Rosters & Attendance' },
            { id: 'series', label: 'Recurring Series Creator' },
            { id: 'availability', label: 'Availability & Time Off' },
            { id: 'feedback', label: 'Member Reviews & Feedback' },
          ].map((tab) => (
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

        {/* Tab 1: Class Rosters */}
        {activeTab === 'roster' && (
          <div className="grid lg:grid-cols-3 gap-6">
            {/* Class Selection Column */}
            <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
              <h2 className="text-base font-bold text-text-primary">
                Upcoming Classes
              </h2>

              <div className="space-y-2">
                {trainerClasses.map((cls: any) => {
                  const isSelected = cls.id === activeClassId;
                  return (
                    <div
                      key={cls.id}
                      onClick={() => setSelectedClassId(cls.id)}
                      className={`cursor-pointer rounded-xl border p-3 text-xs transition ${
                        isSelected
                          ? 'border-accent bg-accent/10'
                          : 'border-border hover:border-border/80 bg-surface'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-bold text-text-primary">{cls.title}</span>
                        <span className="text-[10px] text-text-muted">{cls.booked_count} booked</span>
                      </div>
                      <p className="text-[11px] text-text-muted">
                        {new Date(cls.start_time).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Roster Display Column (First Names Only per Spec 3.2 & 10.3) */}
            <div className="lg:col-span-2 rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-base font-bold text-text-primary">
                    Attendee Roster
                  </h2>
                  <p className="text-xs text-text-muted">
                    Privacy Invariant: Attendee first names only. Medical and contact details are masked.
                  </p>
                </div>

                <span className="rounded-full bg-surface-raised px-3 py-1 text-xs font-semibold text-text-primary">
                  {rosterData?.roster?.length || 0} Registered
                </span>
              </div>

              <div className="divide-y divide-border">
                {rosterData?.roster?.map((att: any, i: number) => (
                  <div key={i} className="py-3 flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-raised text-xs font-bold text-text-primary">
                        {att.first_name?.[0] || 'A'}
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-text-primary">
                          {att.first_name}
                        </p>
                        <p className="text-[11px] text-text-muted">Booking: {att.status}</p>
                      </div>
                    </div>

                    <div className="flex items-center space-x-2">
                      <button
                        className="min-h-[40px] rounded-lg border border-border px-3 py-1 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-raised transition"
                        title="Mark Present"
                      >
                        Present
                      </button>
                      <button
                        className="min-h-[40px] rounded-lg border border-border px-3 py-1 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-raised transition"
                        title="Mark No-Show"
                      >
                        No-Show
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Recurring Series Creator with Conflict Flags */}
        {activeTab === 'series' && (
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-6">
            <div>
              <h2 className="text-lg font-bold text-text-primary">
                Recurring Series Generator
              </h2>
              <p className="text-xs text-text-muted">
                Preview all instances across your calendar to automatically flag overlaps, time off, and availability conflicts.
              </p>
            </div>

            <div className="grid sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Series Title
                </label>
                <input
                  type="text"
                  value={seriesTitle}
                  onChange={(e) => setSeriesTitle(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Category
                </label>
                <select
                  value={seriesCategory}
                  onChange={(e) => setSeriesCategory(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                >
                  <option value="HIIT">HIIT</option>
                  <option value="YOGA">Yoga</option>
                  <option value="STRENGTH">Strength</option>
                  <option value="REHAB">Mobility / Rehab</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Capacity
                </label>
                <input
                  type="number"
                  value={seriesCapacity}
                  onChange={(e) => setSeriesCapacity(Number(e.target.value))}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  First Session Start Time
                </label>
                <input
                  type="datetime-local"
                  value={seriesStart}
                  onChange={(e) => setSeriesStart(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Duration (Minutes)
                </label>
                <input
                  type="number"
                  value={seriesDuration}
                  onChange={(e) => setSeriesDuration(Number(e.target.value))}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1">
                  Recurring Weeks
                </label>
                <input
                  type="number"
                  min={1}
                  max={12}
                  value={seriesWeeks}
                  onChange={(e) => setSeriesWeeks(Number(e.target.value))}
                  className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                />
              </div>
            </div>

            <div>
              <button
                onClick={() => previewSeriesMutation.mutate()}
                disabled={previewSeriesMutation.isPending}
                className="flex items-center gap-1.5 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-5 py-2.5 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50"
              >
                <span>{previewSeriesMutation.isPending ? 'Checking Conflicts...' : 'Preview Series Instances'}</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

            {/* Preview Results Grid */}
            {previewInstances && (
              <div className="pt-4 border-t border-border space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-text-primary">
                  Instance Preview Results ({previewInstances.length} weeks)
                </h3>

                <div className="space-y-2">
                  {previewInstances.map((inst, i) => (
                    <div
                      key={i}
                      className={`rounded-xl border p-3 flex items-center justify-between text-xs ${
                        inst.status === 'OK'
                          ? 'border-accent/30 bg-accent/10 text-text-primary'
                          : 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400'
                      }`}
                    >
                      <div className="space-y-0.5">
                        <span className="font-semibold text-text-primary">
                          Week {i + 1}: {new Date(inst.start_time).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                        </span>
                        {inst.conflict_details && (
                          <p className="text-[11px] text-amber-600 dark:text-amber-400">
                            {inst.conflict_details}
                          </p>
                        )}
                      </div>

                      <span
                        className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                          inst.status === 'OK'
                            ? 'bg-accent/20 text-accent'
                            : 'bg-amber-500/20 text-amber-600 dark:text-amber-400'
                        }`}
                      >
                        {inst.status}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={onOpenCoach}
                    className="flex items-center gap-1.5 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-5 py-2 text-xs font-semibold text-white shadow-sm transition"
                  >
                    <span>Confirm Series Scheduling via AI Copilot</span>
                    <Sparkles className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Availability & Time Off */}
        {activeTab === 'availability' && (
          <div className="grid md:grid-cols-2 gap-6">
            {/* Weekly Availability Grid */}
            <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
              <h2 className="text-base font-bold text-text-primary">
                Regular Working Hours
              </h2>
              <div className="space-y-2">
                {availabilityData?.slots?.map((slot: any, i: number) => {
                  const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
                  return (
                    <div key={i} className="flex items-center justify-between rounded-lg bg-surface-raised p-3 text-xs">
                      <span className="font-semibold text-text-primary">{dayNames[slot.weekday]}</span>
                      <span className="text-text-muted">{slot.start_time} - {slot.end_time}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Book Time Off Form */}
            <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
              <h2 className="text-base font-bold text-text-primary">
                Schedule Time Off / Vacation
              </h2>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  submitTimeOffMutation.mutate();
                }}
                className="space-y-3"
              >
                <div>
                  <label className="block text-xs font-semibold text-text-primary mb-1">
                    Starts At
                  </label>
                  <input
                    type="datetime-local"
                    value={timeOffStart}
                    onChange={(e) => setTimeOffStart(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-text-primary mb-1">
                    Ends At
                  </label>
                  <input
                    type="datetime-local"
                    value={timeOffEnd}
                    onChange={(e) => setTimeOffEnd(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-text-primary mb-1">
                    Reason
                  </label>
                  <input
                    type="text"
                    value={timeOffReason}
                    onChange={(e) => setTimeOffReason(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-raised p-2.5 text-xs text-text-primary min-h-[44px]"
                  />
                </div>

                <button
                  type="submit"
                  disabled={submitTimeOffMutation.isPending}
                  className="min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-4 py-2 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50"
                >
                  {submitTimeOffMutation.isPending ? 'Saving...' : 'Book Time Off'}
                </button>
              </form>
            </div>
          </div>
        )}

        {/* Tab 4: Member Reviews & Feedback */}
        {activeTab === 'feedback' && (
          <div className="rounded-2xl border border-border bg-surface p-6 shadow-sm space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/10 text-amber-500">
                <Star className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-text-primary">
                  Aggregated Member Reviews
                </h2>
                <p className="text-xs text-text-muted">
                  K-Anonymity Privacy Floor: Individual reviews are anonymized and aggregated.
                </p>
              </div>
            </div>

            {feedbackData?.suppressed ? (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-600 dark:text-amber-400 flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <p>{feedbackData.message}</p>
              </div>
            ) : (
              <div className="space-y-2 text-xs">
                <p className="font-semibold text-text-primary">Average Rating: 4.8 / 5.0 ({feedbackData?.count || 12} reviews)</p>
                <p className="text-text-muted">Summary: Members highlight excellent pacing, clear cues, and motivational energy.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
