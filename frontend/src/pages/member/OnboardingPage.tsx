// src/pages/member/OnboardingPage.tsx
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import {
  ShieldCheck,
  ArrowRight,
  ArrowLeft,
  Sparkles,
  AlertTriangle,
} from 'lucide-react';
import { client } from '../../api/client';
import { useAuth } from '../../auth/AuthContext';

export const OnboardingPage: React.FC = () => {
  const navigate = useNavigate();
  const { refreshMe } = useAuth();

  const [step, setStep] = useState(1);

  // Form State
  const [dateOfBirth, setDateOfBirth] = useState('1995-05-15');
  const [gender, setGender] = useState('FEMALE');
  const [heightCm, setHeightCm] = useState(165);
  const [weightKg, setWeightKg] = useState(62);
  const [experienceLevel, setExperienceLevel] = useState('BEGINNER');

  const [goal, setGoal] = useState('FAT_LOSS');
  const [preferredActivities, setPreferredActivities] = useState<string[]>(['YOGA', 'HIIT']);

  const [knownInjuries, setKnownInjuries] = useState<string[]>(['KNEE']);
  const [allergies, setAllergies] = useState<string[]>(['PEANUT']);
  const [medicalNotes, setMedicalNotes] = useState('');

  const [healthConsent, setHealthConsent] = useState(true);

  const toggleArrayItem = (arr: string[], item: string, setter: (val: string[]) => void) => {
    if (arr.includes(item)) {
      setter(arr.filter((x) => x !== item));
    } else {
      setter([...arr, item]);
    }
  };

  const saveIntakeMutation = useMutation({
    mutationFn: async () => {
      // 1. If consent is affirmative, grant consent
      if (healthConsent) {
        await client.post('/me/consent', { consent: true });
      }

      // 2. Save intake details
      const payload = {
        date_of_birth: dateOfBirth,
        gender,
        height_cm: Number(heightCm),
        weight_kg: Number(weightKg),
        experience_level: experienceLevel,
        goal,
        preferred_activities: preferredActivities,
        known_injuries: knownInjuries,
        allergies,
        medical_notes: medicalNotes,
      };

      await client.put('/me/intake', payload);
      await refreshMe();
    },
    onSuccess: () => {
      navigate('/app');
    },
  });

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 dark:bg-slate-950 py-12 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-2xl">
        {/* Progress Tracker */}
        <div className="mb-8">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2">
            <span>Step {step} of 4</span>
            <span>
              {step === 1 && 'Basics & Body Metrics'}
              {step === 2 && 'Goals & Interests'}
              {step === 3 && 'Injuries & Dietary Allergies'}
              {step === 4 && 'Health Consent & Confirmation'}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all duration-300"
              style={{ width: `${(step / 4) * 100}%` }}
            />
          </div>
        </div>

        {/* Card Content */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-8 shadow-sm">
          {step === 1 && (
            <div className="space-y-6">
              <div>
                <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Tell us about yourself</h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  These metrics calibrate deterministic BMR, TDEE, and hydration calculators.
                </p>
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Date of Birth
                  </label>
                  <input
                    type="date"
                    value={dateOfBirth}
                    onChange={(e) => setDateOfBirth(e.target.value)}
                    className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3.5 py-2.5 text-sm text-slate-900 dark:text-white"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Biological Gender
                  </label>
                  <select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                    className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3.5 py-2.5 text-sm text-slate-900 dark:text-white"
                  >
                    <option value="FEMALE">Female</option>
                    <option value="MALE">Male</option>
                    <option value="OTHER">Other / Non-binary</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Height (cm)
                  </label>
                  <input
                    type="number"
                    value={heightCm}
                    onChange={(e) => setHeightCm(Number(e.target.value))}
                    className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3.5 py-2.5 text-sm text-slate-900 dark:text-white"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Weight (kg)
                  </label>
                  <input
                    type="number"
                    value={weightKg}
                    onChange={(e) => setWeightKg(Number(e.target.value))}
                    className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3.5 py-2.5 text-sm text-slate-900 dark:text-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  Training Experience
                </label>
                <div className="grid grid-cols-3 gap-3">
                  {['BEGINNER', 'INTERMEDIATE', 'ADVANCED'].map((lvl) => (
                    <button
                      key={lvl}
                      type="button"
                      onClick={() => setExperienceLevel(lvl)}
                      className={`rounded-xl border p-3 text-xs font-semibold transition ${
                        experienceLevel === lvl
                          ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300'
                          : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
                      }`}
                    >
                      {lvl}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-6">
              <div>
                <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Primary Goal & Activities</h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Select your primary fitness objective and activities you enjoy.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  Primary Goal
                </label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {[
                    { id: 'FAT_LOSS', label: 'Fat Loss' },
                    { id: 'HYPERTROPHY', label: 'Muscle Growth' },
                    { id: 'STRENGTH', label: 'Raw Strength' },
                    { id: 'ENDURANCE', label: 'Endurance' },
                    { id: 'MAINTENANCE', label: 'General Health' },
                  ].map((g) => (
                    <button
                      key={g.id}
                      type="button"
                      onClick={() => setGoal(g.id)}
                      className={`rounded-xl border p-3 text-xs font-semibold transition ${
                        goal === g.id
                          ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300'
                          : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
                      }`}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  Preferred Activities
                </label>
                <div className="flex flex-wrap gap-2">
                  {['YOGA', 'HIIT', 'STRENGTH', 'CARDIO', 'PILATES', 'CYCLING'].map((act) => {
                    const active = preferredActivities.includes(act);
                    return (
                      <button
                        key={act}
                        type="button"
                        onClick={() => toggleArrayItem(preferredActivities, act, setPreferredActivities)}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                          active
                            ? 'bg-emerald-600 text-white'
                            : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {act}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-6">
              <div>
                <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Injuries & Dietary Allergens</h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Critical safety parameters. The AI will strictly filter out contraindicated exercises and foods.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  Known Injuries (Filters classes & exercises)
                </label>
                <div className="flex flex-wrap gap-2">
                  {['KNEE', 'LOWER_BACK', 'SHOULDER', 'WRIST', 'ANKLE', 'NECK'].map((inj) => {
                    const active = knownInjuries.includes(inj);
                    return (
                      <button
                        key={inj}
                        type="button"
                        onClick={() => toggleArrayItem(knownInjuries, inj, setKnownInjuries)}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                          active
                            ? 'bg-amber-600 text-white'
                            : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {inj}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  Food Allergens (Fail-closed meal recommendations)
                </label>
                <div className="flex flex-wrap gap-2">
                  {['PEANUT', 'DAIRY', 'GLUTEN', 'SHELLFISH', 'TREE_NUT', 'SOY', 'EGG'].map((allg) => {
                    const active = allergies.includes(allg);
                    return (
                      <button
                        key={allg}
                        type="button"
                        onClick={() => toggleArrayItem(allergies, allg, setAllergies)}
                        className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                          active
                            ? 'bg-red-600 text-white'
                            : 'border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        {allg}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Additional Medical Notes (Optional)
                </label>
                <textarea
                  rows={2}
                  value={medicalNotes}
                  onChange={(e) => setMedicalNotes(e.target.value)}
                  placeholder="e.g. Mild asthma during intense cardio, recovering from sprain"
                  className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 p-3 text-xs text-slate-900 dark:text-white"
                />
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-6">
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                  <ShieldCheck className="h-6 w-6" />
                </div>
                <div>
                  <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Health-Data Consent</h2>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    GDPR and Health Information Privacy Protection
                  </p>
                </div>
              </div>

              <div className="rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50/50 dark:bg-emerald-950/20 p-5 space-y-3 text-xs text-slate-700 dark:text-slate-300">
                <p className="font-semibold text-emerald-900 dark:text-emerald-300">
                  How GymPro AI processes your health data:
                </p>
                <ul className="list-disc pl-4 space-y-1 text-slate-600 dark:text-slate-400">
                  <li>Your injuries and allergies are used to protect you from unsafe classes and meals.</li>
                  <li>Trainers and staff never see your medical history or injury notes.</li>
                  <li>You can withdraw consent at any time from your Privacy page.</li>
                  <li>Withdrawing consent immediately deletes your biometric intake profile and clears AI memory.</li>
                </ul>

                <div className="pt-2 border-t border-emerald-200 dark:border-emerald-900/50 flex items-start gap-3">
                  <input
                    type="checkbox"
                    id="consent"
                    checked={healthConsent}
                    onChange={(e) => setHealthConsent(e.target.checked)}
                    className="h-4 w-4 rounded border-emerald-300 text-emerald-600 focus:ring-emerald-500 mt-0.5"
                  />
                  <label htmlFor="consent" className="font-medium text-slate-800 dark:text-slate-200">
                    I grant affirmative consent for GymPro AI to store and process my biometric, injury, and dietary data for personalized coaching.
                  </label>
                </div>
              </div>

              {!healthConsent && (
                <div className="flex items-center gap-2 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 p-3 text-xs text-amber-800 dark:text-amber-300">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>
                    Without health consent, AI coaching will run in generic mode without injury filtering or macro personalization.
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Navigation Controls */}
          <div className="mt-8 flex items-center justify-between pt-4 border-t border-slate-100 dark:border-slate-800">
            {step > 1 ? (
              <button
                type="button"
                onClick={() => setStep((s) => s - 1)}
                className="flex items-center gap-1.5 rounded-xl border border-slate-300 dark:border-slate-700 px-4 py-2.5 text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition"
              >
                <ArrowLeft className="h-4 w-4" /> Back
              </button>
            ) : (
              <div />
            )}

            {step < 4 ? (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                className="flex items-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 px-5 py-2.5 text-xs font-semibold text-white shadow-sm transition"
              >
                Continue <ArrowRight className="h-4 w-4" />
              </button>
            ) : (
              <button
                type="button"
                disabled={saveIntakeMutation.isPending}
                onClick={() => saveIntakeMutation.mutate()}
                className="flex items-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 px-6 py-2.5 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50"
              >
                {saveIntakeMutation.isPending ? 'Saving...' : 'Complete Onboarding'}
                <Sparkles className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
