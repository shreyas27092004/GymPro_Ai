// src/pages/member/MembershipPage.tsx
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CreditCard,
  CheckCircle,
  Zap,
  AlertCircle,
  HelpCircle,
  ArrowRight,
} from 'lucide-react';
import { client, friendlyError } from '../../api/client';
import { openCheckout, type Checkout } from '../../payments/openCheckout';
import { useAuth } from '../../auth/AuthContext';

export const MembershipPage: React.FC = () => {
  const { me, refreshMe } = useAuth();
  const queryClient = useQueryClient();

  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // 1. Fetch current membership
  const { data: currentMembership } = useQuery({
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

  // 2. Fetch available plans
  const { data: plans = [] } = useQuery({
    queryKey: ['plans-list'],
    queryFn: async () => {
      try {
        const res = await client.get('/plans');
        return res.data || [];
      } catch {
        return [
          {
            code: 'SILVER',
            name: 'Silver Tier',
            price_monthly: 999.0,
            classes_per_month: 8,
            perks: ['Standard group classes', 'Basic locker access'],
          },
          {
            code: 'GOLD',
            name: 'Gold Tier',
            price_monthly: 1999.0,
            classes_per_month: 20,
            perks: ['All group classes', 'Yoga & Pilates', 'Free guest pass per month'],
          },
          {
            code: 'PLATINUM',
            name: 'Platinum Tier',
            price_monthly: 3499.0,
            classes_per_month: 999,
            perks: [
              'Unlimited classes',
              'Priority booking cut-off',
              '1-on-1 trainer assessment',
              'Towel & sauna service',
            ],
          },
        ];
      }
    },
  });

  // Direct upgrade flow via propose / checkout
  const handleUpgradeClick = async (planCode: string) => {
    setSelectedPlan(planCode);
    setStatusMsg(null);
    setUpgrading(true);

    try {
      // 1. Propose membership upgrade
      const proposeRes = await client.post('/actions/propose-plan-change', {
        new_plan: planCode,
      });

      const actionId = proposeRes.data?.action_id;
      if (!actionId) {
        throw new Error('Could not initialize plan upgrade.');
      }

      // 2. Confirm action to initiate payment
      const confirmRes = await client.post(`/actions/${actionId}/confirm`);

      if (confirmRes.data?.status === 'AWAITING_PAYMENT' && confirmRes.data?.payment) {
        const checkoutObj = confirmRes.data.payment as Checkout;
        const payRes = await openCheckout(checkoutObj, {
          name: me?.full_name || 'Member',
          email: me?.email_masked || 'member@gympro.test',
        });

        if (payRes === 'DISMISSED') {
          setStatusMsg({
            type: 'error',
            text: 'Payment was dismissed. You can reopen checkout at any time.',
          });
        } else if (payRes.ok) {
          setStatusMsg({
            type: 'success',
            text: `Successfully upgraded to ${planCode} membership!`,
          });
          await refreshMe();
          queryClient.invalidateQueries({ queryKey: ['me-membership'] });
        } else {
          setStatusMsg({
            type: 'error',
            text: `Payment failed: ${payRes.error || 'Verification error'}.`,
          });
        }
      } else if (confirmRes.data?.ok) {
        setStatusMsg({
          type: 'success',
          text: `Membership updated to ${planCode}!`,
        });
        await refreshMe();
        queryClient.invalidateQueries({ queryKey: ['me-membership'] });
      }
    } catch (e: any) {
      setStatusMsg({
        type: 'error',
        text: friendlyError(e),
      });
    } finally {
      setUpgrading(false);
    }
  };

  const currentPlanCode = currentMembership?.plan_code || currentMembership?.plan || 'NONE';

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 dark:bg-slate-950 py-12 px-4 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-6xl space-y-10">
        <div className="text-center space-y-2 max-w-2xl mx-auto">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <CreditCard className="h-5 w-5" />
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 dark:text-white">
            Membership Plans & Upgrades
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Transparent pricing with prorated billing. All payments are secured via Razorpay.
          </p>
        </div>

        {statusMsg && (
          <div
            className={`flex items-center gap-2.5 rounded-xl p-4 text-xs font-medium max-w-xl mx-auto ${
              statusMsg.type === 'success'
                ? 'bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
                : 'bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-300'
            }`}
          >
            {statusMsg.type === 'success' ? (
              <CheckCircle className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
            )}
            <span>{statusMsg.text}</span>
          </div>
        )}

        {/* Current Plan Banner */}
        <div className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <Zap className="h-6 w-6" />
            </div>
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Active Tier
              </span>
              <h3 className="text-xl font-bold text-slate-900 dark:text-white">
                {currentPlanCode !== 'NONE' ? `${currentPlanCode} Membership` : 'Free Trial / Non-Member'}
              </h3>
            </div>
          </div>

          <div className="text-right">
            <span className="rounded-full bg-emerald-100 dark:bg-emerald-950 px-3 py-1 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
              {currentMembership?.status || 'ACTIVE'}
            </span>
            {currentMembership?.end_date && (
              <p className="text-[11px] text-slate-400 mt-1">Renews {currentMembership.end_date}</p>
            )}
          </div>
        </div>

        {/* Plan Comparison Cards */}
        <div className="grid md:grid-cols-3 gap-6">
          {plans.map((p: any) => {
            const isCurrent = currentPlanCode === p.code;
            return (
              <div
                key={p.code}
                className={`rounded-2xl border p-6 flex flex-col justify-between transition shadow-sm ${
                  isCurrent
                    ? 'border-emerald-500 bg-emerald-50/20 dark:bg-emerald-950/10 ring-2 ring-emerald-500/20'
                    : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-lg font-bold text-slate-900 dark:text-white">{p.name || p.code}</h3>
                    {isCurrent && (
                      <span className="rounded bg-emerald-100 dark:bg-emerald-900/60 px-2 py-0.5 text-[10px] font-bold text-emerald-800 dark:text-emerald-300">
                        Current
                      </span>
                    )}
                  </div>

                  <div className="mt-3 flex items-baseline gap-1">
                    <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
                      ₹{p.price_monthly}
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">/ month</span>
                  </div>

                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                    {p.classes_per_month > 100
                      ? 'Unlimited access to all classes'
                      : `Includes ${p.classes_per_month} classes per monthly cycle`}
                  </p>

                  <ul className="mt-6 space-y-2.5 text-xs text-slate-600 dark:text-slate-300">
                    {(p.perks || []).map((perk: string, i: number) => (
                      <li key={i} className="flex items-center gap-2">
                        <CheckCircle className="h-4 w-4 text-emerald-500 shrink-0" />
                        <span>{perk}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="mt-8 pt-4 border-t border-slate-100 dark:border-slate-800">
                  {isCurrent ? (
                    <button
                      disabled
                      className="w-full rounded-xl bg-slate-100 dark:bg-slate-800 py-2.5 text-xs font-semibold text-slate-500 dark:text-slate-400 cursor-default"
                    >
                      Active Plan
                    </button>
                  ) : (
                    <button
                      disabled={upgrading}
                      onClick={() => handleUpgradeClick(p.code)}
                      className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 py-2.5 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50"
                    >
                      <span>{upgrading && selectedPlan === p.code ? 'Processing...' : `Upgrade to ${p.code}`}</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Downgrade Policy Notice */}
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-slate-900 p-4 text-xs text-slate-600 dark:text-slate-400 flex items-start gap-3">
          <HelpCircle className="h-4 w-4 text-slate-500 mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold text-slate-800 dark:text-slate-200">
              Downgrades Policy (Decision 13)
            </p>
            <p className="mt-0.5">
              To prevent mid-cycle disruption of class entitlements and booking allocations, plan downgrades are processed exclusively at the end of the current billing cycle by gym staff. Please contact front desk or support if you wish to set your renewal tier.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
