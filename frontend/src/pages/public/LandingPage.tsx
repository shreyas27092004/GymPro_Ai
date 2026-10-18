// src/pages/public/LandingPage.tsx
import React from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ShieldCheck,
  Sparkles,
  Zap,
  ArrowRight,
  Bot,
  CheckCircle,
} from 'lucide-react';

export const LandingPage: React.FC = () => {
  return (
    <div className="flex flex-col min-h-[calc(100vh-4rem)] bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      {/* Hero Section */}
      <section className="relative overflow-hidden py-16 sm:py-24 lg:py-32 border-b border-slate-200 dark:border-slate-800">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center space-y-6 max-w-3xl mx-auto">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
              <Sparkles className="h-3.5 w-3.5" />
              <span>Enterprise Autonomous Gym Operations</span>
            </div>

            <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-slate-900 dark:text-white">
              The AI-First Gym Platform With{' '}
              <span className="text-emerald-600 dark:text-emerald-400">Strict Human Safety</span>
            </h1>

            <p className="text-lg text-slate-600 dark:text-slate-400">
              Multi-agent architecture orchestrating workouts, schedules, nutrition, and member operations.
              Agents <span className="font-semibold text-slate-800 dark:text-slate-200">propose</span>;
              members and staff <span className="font-semibold text-slate-800 dark:text-slate-200">confirm</span>;
              and deterministic backend code executes safely.
            </p>

            <div className="flex flex-wrap justify-center gap-4 pt-4">
              <Link
                to="/register"
                className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 px-6 py-3.5 text-base font-semibold text-white shadow-lg shadow-emerald-600/20 transition"
              >
                <span>Get Started</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                to="/login"
                className="inline-flex items-center gap-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-6 py-3.5 text-base font-semibold text-slate-800 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition"
              >
                Sign In
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* 3 Role Consoles Feature Grid */}
      <section className="py-16 sm:py-24 bg-white dark:bg-slate-900/50 border-b border-slate-200 dark:border-slate-800">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
              Built for Members, Trainers, and Gym Governance
            </h2>
            <p className="mt-3 text-slate-600 dark:text-slate-400 text-sm">
              Role-separated interfaces with PostgreSQL Row-Level Security and strict authorization invariants.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {/* Member */}
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 p-8 shadow-sm">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 mb-6">
                <Zap className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-slate-900 dark:text-white mb-3">Member AI Coach</h3>
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-6">
                Personalized fitness, wellness, and nutrition guidance. Injury-safe class booking, trial management, and multi-step action bundles.
              </p>
              <ul className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-500" />
                  <span>Deterministic BMR & macro calculators</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-500" />
                  <span>Affirmative health data consent controls</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-500" />
                  <span>One-tap Razorpay membership upgrades</span>
                </li>
              </ul>
            </div>

            {/* Trainer */}
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 p-8 shadow-sm">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 mb-6">
                <Activity className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-slate-900 dark:text-white mb-3">Trainer Ops Console</h3>
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-6">
                Manage weekly availability, schedule recurring class series with automatic conflict detection, view privacy-safe rosters, and inspect feedback.
              </p>
              <ul className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-blue-500" />
                  <span>Series preview with overlap & time-off flags</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-blue-500" />
                  <span>First-name only attendee roster privacy</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-blue-500" />
                  <span>K-anonymity aggregated feedback floor</span>
                </li>
              </ul>
            </div>

            {/* Admin */}
            <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 p-8 shadow-sm">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-purple-500/10 text-purple-600 dark:text-purple-400 mb-6">
                <ShieldCheck className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-slate-900 dark:text-white mb-3">Admin Governance</h3>
              <p className="text-sm text-slate-600 dark:text-slate-400 mb-6">
                Executive metric catalog views, trainer request approvals queue, HMAC one-time-code admin activation, issue triage, and broadcast drafts.
              </p>
              <ul className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-purple-500" />
                  <span>No LLM free SQL; metric catalog only</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-purple-500" />
                  <span>24-hour cooling-off protection on sensitive tasks</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-purple-500" />
                  <span>Strict zero-privilege escalation defense</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Safety Invariants Callout */}
      <section className="py-12 bg-slate-100 dark:bg-slate-950">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 text-center space-y-4">
          <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 dark:text-slate-400">
            <Bot className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            <span>Audited & Verified Safety Architecture</span>
          </div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">
            10 Domain Agents. 1 Supervisor DAG. 0 Direct LLM Database Writes.
          </h2>
          <p className="text-sm text-slate-600 dark:text-slate-400 max-w-2xl mx-auto">
            Every propose tool writes to an unconfirmed pending state. The client only sees verified cards. All writes execute through transactional deterministic handlers.
          </p>
        </div>
      </section>
    </div>
  );
};
