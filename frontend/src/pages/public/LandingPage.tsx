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
    <div className="flex flex-col min-h-[calc(100vh-4rem)] bg-base text-text-primary">
      {/* Hero Section */}
      <section className="relative overflow-hidden py-16 sm:py-24 lg:py-32 border-b border-border">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center space-y-6 max-w-3xl mx-auto">
            <div className="inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent/10 px-3 py-1 text-xs font-semibold text-accent">
              <Sparkles className="h-3.5 w-3.5" />
              <span>Enterprise Autonomous Gym Operations</span>
            </div>

            <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-text-primary">
              The AI-First Gym Platform With{' '}
              <span className="text-accent">Strict Human Safety</span>
            </h1>

            <p className="text-lg text-text-muted">
              Multi-agent architecture orchestrating workouts, schedules, nutrition, and member operations.
              Agents <span className="font-semibold text-text-primary">propose</span>;
              members and staff <span className="font-semibold text-text-primary">confirm</span>;
              and deterministic backend code executes safely.
            </p>

            <div className="flex flex-wrap justify-center gap-4 pt-4">
              <Link
                to="/register"
                className="inline-flex items-center gap-2 min-h-[44px] rounded-xl bg-accent hover:bg-accent-hover px-6 py-3 text-base font-semibold text-white shadow-lg shadow-accent/20 transition"
              >
                <span>Get Started</span>
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                to="/login"
                className="inline-flex items-center gap-2 min-h-[44px] rounded-xl border border-border bg-surface px-6 py-3 text-base font-semibold text-text-primary hover:bg-surface-raised transition"
              >
                Sign In
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* 3 Role Consoles Feature Grid */}
      <section className="py-16 sm:py-24 bg-surface border-b border-border">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold tracking-tight text-text-primary">
              Built for Members, Trainers, and Gym Governance
            </h2>
            <p className="mt-3 text-text-muted text-sm">
              Role-separated interfaces with PostgreSQL Row-Level Security and strict authorization invariants.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {/* Member */}
            <div className="rounded-2xl border border-border bg-surface-raised p-8 shadow-sm">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent mb-6">
                <Zap className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-text-primary mb-3">Member AI Coach</h3>
              <p className="text-sm text-text-muted mb-6">
                Personalized fitness, wellness, and nutrition guidance. Injury-safe class booking, trial management, and multi-step action bundles.
              </p>
              <ul className="space-y-2 text-xs text-text-muted">
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>Deterministic BMR & macro calculators</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>Affirmative health data consent controls</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>One-tap Razorpay membership upgrades</span>
                </li>
              </ul>
            </div>

            {/* Trainer */}
            <div className="rounded-2xl border border-border bg-surface-raised p-8 shadow-sm">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent mb-6">
                <Activity className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-text-primary mb-3">Trainer Ops Console</h3>
              <p className="text-sm text-text-muted mb-6">
                Manage weekly availability, schedule recurring class series with automatic conflict detection, view privacy-safe rosters, and inspect feedback.
              </p>
              <ul className="space-y-2 text-xs text-text-muted">
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>Series preview with overlap & time-off flags</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>First-name only attendee roster privacy</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>K-anonymity aggregated feedback floor</span>
                </li>
              </ul>
            </div>

            {/* Admin */}
            <div className="rounded-2xl border border-border bg-surface-raised p-8 shadow-sm">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent mb-6">
                <ShieldCheck className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-bold text-text-primary mb-3">Admin Governance</h3>
              <p className="text-sm text-text-muted mb-6">
                Executive metric catalog views, trainer request approvals queue, HMAC one-time-code admin activation, issue triage, and broadcast drafts.
              </p>
              <ul className="space-y-2 text-xs text-text-muted">
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>No LLM free SQL; metric catalog only</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>24-hour cooling-off protection on sensitive tasks</span>
                </li>
                <li className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-accent" />
                  <span>Strict zero-privilege escalation defense</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Safety Invariants Callout */}
      <section className="py-12 bg-base border-t border-border">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 text-center space-y-4">
          <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-text-muted">
            <Bot className="h-4 w-4 text-accent" />
            <span>Audited & Verified Safety Architecture</span>
          </div>
          <h2 className="text-2xl font-bold text-text-primary">
            10 Domain Agents. 1 Supervisor DAG. 0 Direct LLM Database Writes.
          </h2>
          <p className="text-sm text-text-muted max-w-2xl mx-auto">
            Every propose tool writes to an unconfirmed pending state. The client only sees verified cards. All writes execute through transactional deterministic handlers.
          </p>
        </div>
      </section>
    </div>
  );
};
