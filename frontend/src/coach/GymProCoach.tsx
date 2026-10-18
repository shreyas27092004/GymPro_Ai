// src/coach/GymProCoach.tsx
import React, { useRef, useState, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  Mic,
  MicOff,
  Send,
  ShieldCheck,
  Volume2,
  VolumeX,
  X,
  Bot,
  Sparkles,
  CreditCard,
  Ban,
} from 'lucide-react';
import { client, friendlyError } from '../api/client';
import { openCheckout, type Checkout } from '../payments/openCheckout';
import { useAuth } from '../auth/AuthContext';
import type { ChatMessage, Bundle } from '../types';

interface GymProCoachProps {
  isOpen: boolean;
  onClose: () => void;
  conversationId?: string;
}

export const GymProCoach: React.FC<GymProCoachProps> = ({
  isOpen,
  onClose,
  conversationId = 'default',
}) => {
  const { me } = useAuth();
  const drawerRef = useRef<HTMLDivElement>(null);

  // Pending payment state for "Pay now" and "Cancel payment"
  const [pendingPayment, setPendingPayment] = useState<{
    payment: Checkout;
    paymentId: string;
  } | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'hello',
      sender: 'agent',
      text:
        me?.role === 'ADMIN'
          ? 'Hi Admin! I can provide operational analytics from the metric catalog, assist with issue triage, and draft member broadcasts.'
          : me?.role === 'TRAINER'
          ? 'Hi Coach! I can help you inspect class rosters, manage your weekly availability and time off, or preview and schedule recurring class series.'
          : 'Hi! I can help with classes, trainers, workouts, wellness, nutrition, your membership and problem reports.',
      actions:
        me?.role === 'ADMIN'
          ? [
              { type: 'PROMPT', label: 'Show active occupancy and MRR' },
              { type: 'PROMPT', label: 'Which classes are under 40% full?' },
              { type: 'PROMPT', label: 'Summarize today daily digest' },
            ]
          : me?.role === 'TRAINER'
          ? [
              { type: 'PROMPT', label: 'Show my availability and time off' },
              { type: 'PROMPT', label: 'Schedule HIIT Mon/Wed/Fri 6 PM for 4 weeks' },
              { type: 'PROMPT', label: 'Show my latest member feedback' },
            ]
          : [
              { type: 'PROMPT', label: 'Book tomorrow evening yoga' },
              { type: 'PROMPT', label: 'Which class is safe for my knee?' },
              { type: 'PROMPT', label: 'Upgrade to Gold membership' },
            ],
    },
  ]);

  const [input, setInput] = useState('');
  const [listening, setListening] = useState(false);
  const [speak, setSpeak] = useState(false);
  const recRef = useRef<any>(null);

  // Focus trap & Escape key listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  const push = (m: Omit<ChatMessage, 'id'>) => {
    const msg: ChatMessage = { ...m, id: crypto.randomUUID() };
    setMessages((p) => [...p, msg]);
    if (speak && m.sender === 'agent' && typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(m.text));
    }
  };

  const chat = useMutation({
    mutationFn: async (message: string) => {
      const res = await client.post('/agent/chat', {
        message,
        conversation_id: conversationId,
        input_mode: listening ? 'voice' : 'text',
      });
      return res.data;
    },
    onSuccess: (d) => {
      push({
        sender: 'agent',
        text: d.reply,
        actions: d.quick_actions,
        bundle: d.bundle?.steps ? (d.bundle as Bundle) : null,
      });
    },
    onError: (e: any) => {
      push({
        sender: 'agent',
        text: friendlyError(e),
      });
    },
  });

  const confirmAction = useMutation({
    mutationFn: async (actionId: string) => {
      const res = await client.post(`/actions/${actionId}/confirm`);
      return { res: res.data, actionId };
    },
    onSuccess: async ({ res: r, actionId }) => {
      setMessages((p) =>
        p.map((m) => ({
          ...m,
          actions: m.actions?.filter((a) => a.type !== 'CONFIRM' || a.action_id !== actionId),
        }))
      );

      if (r.status === 'AWAITING_PAYMENT' && r.payment) {
        setPendingPayment({ payment: r.payment, paymentId: r.payment.payment_id });
        push({ sender: 'agent', text: 'Waiting for payment confirmation. Opening secure checkout...' });
        const payRes = await openCheckout(r.payment, {
          name: me?.full_name || 'Member',
          email: me?.email_masked || 'member@gympro.test',
        });
        if (payRes === 'DISMISSED') {
          push({
            sender: 'agent',
            text: 'Payment was dismissed. You can tap "Pay now" below to complete checkout or "Cancel payment" to abandon.',
          });
        } else if (payRes.ok) {
          setPendingPayment(null);
          push({ sender: 'agent', text: 'Payment confirmed! Your plan change is active.' });
        } else {
          push({ sender: 'agent', text: `Payment could not be completed (${payRes.error || 'Failed'}).` });
        }
        return;
      }

      push({
        sender: 'agent',
        text: r.ok ? 'Confirmed. Your request has executed.' : `Could not complete (${r.error}). Want me to find alternatives?`,
      });
    },
    onError: (e: any) => push({ sender: 'agent', text: friendlyError(e) }),
  });

  const confirmBundle = useMutation({
    mutationFn: async (bundleId: string) => {
      const res = await client.post(`/bundles/${bundleId}/confirm`);
      return { res: res.data, bundleId };
    },
    onSuccess: async ({ res: r, bundleId }) => {
      setMessages((p) =>
        p.map((m) =>
          m.bundle?.bundle_id === bundleId
            ? {
                ...m,
                actions: [],
                bundle: {
                  ...m.bundle!,
                  steps: m.bundle!.steps.map((s) => ({
                    ...s,
                    result: r.steps?.find((x: any) => x.step_no === s.step_no)?.status,
                  })),
                },
              }
            : m
        )
      );

      if (r.status === 'AWAITING_PAYMENT' && r.payment) {
        setPendingPayment({ payment: r.payment, paymentId: r.payment.payment_id });
        push({ sender: 'agent', text: 'Waiting for payment. Opening secure checkout window...' });
        const payRes = await openCheckout(r.payment, {
          name: me?.full_name || 'Member',
          email: me?.email_masked || 'member@gympro.test',
        });
        if (payRes === 'DISMISSED') {
          push({
            sender: 'agent',
            text: 'Payment was dismissed. You can tap "Pay now" below to reopen checkout or "Cancel payment" to skip.',
          });
        } else if (payRes.ok) {
          setPendingPayment(null);
          push({ sender: 'agent', text: 'Payment received! Your bundle steps have finished executing.' });
        } else {
          push({ sender: 'agent', text: `Payment failed (${payRes.error || 'Verification error'}).` });
        }
        return;
      }

      const steps: any[] = r.steps || [];
      const failed = steps.filter((s) => s.status !== 'EXECUTED');
      push({
        sender: 'agent',
        text:
          failed.length === 0
            ? 'All steps completed.'
            : `Some steps could not complete: ${failed
                .map((s) => `step ${s.step_no} ${s.status.toLowerCase()}`)
                .join(', ')}. The independent steps went through.`,
      });
    },
    onError: (e: any) => push({ sender: 'agent', text: friendlyError(e) }),
  });

  // Re-open checkout for pending payment
  const handlePayNow = async () => {
    if (!pendingPayment) return;
    try {
      const payRes = await openCheckout(pendingPayment.payment, {
        name: me?.full_name || 'Member',
        email: me?.email_masked || 'member@gympro.test',
      });
      if (payRes.ok) {
        setPendingPayment(null);
        push({ sender: 'agent', text: 'Payment successful! Action completed.' });
      }
    } catch {
      push({ sender: 'agent', text: 'Checkout could not be loaded.' });
    }
  };

  // Cancel pending payment
  const handleCancelPayment = async () => {
    if (!pendingPayment) return;
    try {
      await client.post(`/payments/${pendingPayment.paymentId}/cancel`);
      setPendingPayment(null);
      push({ sender: 'agent', text: 'Payment cancelled. Associated steps have been skipped.' });
    } catch (e: any) {
      push({ sender: 'agent', text: friendlyError(e) });
    }
  };

  const send = (text: string) => {
    const t = text.trim();
    if (!t || chat.isPending) return;
    push({ sender: 'user', text: t });
    setInput('');
    chat.mutate(t);
  };

  const toggleVoice = () => {
    if (typeof window === 'undefined') return;
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      push({ sender: 'agent', text: 'Voice input is not supported in this browser.' });
      return;
    }
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = new SR();
    rec.lang = navigator.language || 'en-US';
    rec.interimResults = false;
    rec.onresult = (e: any) => {
      const transcript = e.results[0][0].transcript;
      send(transcript);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    rec.start();
    setListening(true);
  };

  const busy = chat.isPending || confirmAction.isPending || confirmBundle.isPending;

  const placeholderText =
    me?.role === 'ADMIN'
      ? 'Try: Which classes are under 40% full?'
      : me?.role === 'TRAINER'
      ? 'Try: Schedule HIIT Mon/Wed/Fri 6 PM for 4 weeks'
      : 'Try: Book tomorrow evening yoga';

  if (!isOpen) return null;

  return (
    <div
      ref={drawerRef}
      className="fixed inset-y-0 right-0 z-50 flex w-full sm:max-w-lg flex-col bg-surface border-l border-border shadow-2xl transition-transform duration-300"
      role="region"
      aria-label="AI fitness coach"
    >
      {/* Header */}
      <header className="flex items-center justify-between border-b border-border bg-surface-raised/50 px-4 py-3 min-h-[56px]">
        <div className="flex items-center space-x-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-sm bg-accent-subtle text-accent">
            <Bot className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h2 className="text-base font-bold text-text-primary">AI Fitness Concierge</h2>
              <span className="flex items-center rounded-sm bg-accent-subtle px-2 py-0.5 text-[10px] font-bold text-accent">
                <Sparkles className="mr-0.5 h-2.5 w-2.5" /> Active
              </span>
            </div>
            <p className="flex items-center gap-1 text-[11px] text-text-muted">
              <ShieldCheck className="h-3.5 w-3.5 text-accent shrink-0" />
              I never change anything until you tap Confirm. Voice never confirms.
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-1">
          <button
            onClick={() => setSpeak((s) => !s)}
            aria-label={speak ? 'Turn off spoken replies' : 'Turn on spoken replies'}
            className="rounded-sm p-2 text-text-muted hover:bg-surface-raised transition min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            {speak ? <Volume2 className="h-5 w-5 text-accent" /> : <VolumeX className="h-5 w-5" />}
          </button>
          <button
            onClick={onClose}
            aria-label="Close assistant"
            className="rounded-sm p-2 text-text-muted hover:bg-surface-raised transition min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
      </header>

      {/* Message List */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4" role="log" aria-live="polite">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[90%] whitespace-pre-line rounded-md p-3.5 text-sm shadow-sm ${
                m.sender === 'user'
                  ? 'bg-accent text-white font-medium'
                  : 'border border-border bg-surface text-text-primary'
              }`}
            >
              {m.text}

              {/* Bundle Card */}
              {m.bundle && (
                <div
                  className="mt-3 space-y-2 rounded-sm border border-border bg-surface-raised/40 p-3 text-xs"
                  aria-label={m.bundle.headline}
                >
                  <div className="font-semibold text-text-primary border-b border-border pb-1.5 flex items-center justify-between">
                    <span>{m.bundle.headline}</span>
                    <span className="text-[10px] text-text-muted font-normal">
                      Expires in 15m
                    </span>
                  </div>
                  <ol className="space-y-2 pt-1">
                    {m.bundle.steps.map((s) => (
                      <li key={s.step_no} className="flex items-start gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-[11px] font-bold text-accent">
                          {s.step_no}
                        </span>
                        <div className="flex-1">
                          <p className="font-medium text-text-primary">{s.summary}</p>
                          {s.depends_on.length > 0 && (
                            <p className="text-[11px] text-text-muted">
                              Goes ahead only if step {s.depends_on.join(', ')} succeeds
                            </p>
                          )}
                          {s.result && (
                            <span
                              className={`mt-1 inline-block rounded-sm px-1.5 py-0.5 text-[10px] font-semibold ${
                                s.result === 'EXECUTED'
                                  ? 'bg-accent-subtle text-accent'
                                  : 'bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300'
                              }`}
                            >
                              {s.result}
                            </span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                  {m.bundle.questions.length > 0 && (
                    <div className="mt-2 border-t border-border pt-2 space-y-1">
                      {m.bundle.questions.map((q, i) => (
                        <p key={i} className="text-[11px] text-text-muted italic">
                          Question from {q.agent}: {q.text}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Quick Actions & Confirm Buttons */}
              {m.actions && m.actions.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {m.actions.map((a, i) =>
                    a.type === 'CONFIRM' ? (
                      <button
                        key={i}
                        disabled={busy}
                        onClick={() => confirmAction.mutate(a.action_id)}
                        className="rounded-sm bg-accent hover:bg-accent-hover px-3 py-2 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50 min-h-[36px]"
                      >
                        Confirm: {a.label}
                      </button>
                    ) : a.type === 'CONFIRM_BUNDLE' ? (
                      <button
                        key={i}
                        disabled={busy}
                        onClick={() => confirmBundle.mutate(a.bundle_id)}
                        className="rounded-sm bg-accent hover:bg-accent-hover px-3 py-2 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50 min-h-[36px]"
                      >
                        Confirm: {a.label}
                      </button>
                    ) : (
                      <button
                        key={i}
                        disabled={busy}
                        onClick={() => send(a.label)}
                        className="rounded-sm border border-border bg-surface px-3 py-2 text-xs font-medium text-text-primary hover:bg-surface-raised transition min-h-[36px]"
                      >
                        {a.label}
                      </button>
                    )
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Pending Payment State (Pay Now / Cancel Payment) */}
        {pendingPayment && (
          <div className="rounded-md border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 p-4 space-y-3">
            <div className="flex items-center gap-2 text-xs font-bold text-amber-900 dark:text-amber-200">
              <CreditCard className="h-4 w-4 text-amber-600" />
              <span>Payment Pending: Waiting for checkout</span>
            </div>
            <p className="text-xs text-amber-800 dark:text-amber-300">
              Your order is ready. Complete the payment to finalize the change, or cancel to abandon.
            </p>
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={handlePayNow}
                className="flex items-center gap-1.5 rounded-sm bg-accent hover:bg-accent-hover px-3.5 py-2 text-xs font-semibold text-white transition min-h-[40px]"
              >
                <CreditCard className="h-3.5 w-3.5" />
                <span>Pay now</span>
              </button>
              <button
                onClick={handleCancelPayment}
                className="flex items-center gap-1.5 rounded-sm border border-border bg-surface px-3.5 py-2 text-xs font-semibold text-danger hover:bg-danger-subtle transition min-h-[40px]"
              >
                <Ban className="h-3.5 w-3.5" />
                <span>Cancel payment</span>
              </button>
            </div>
          </div>
        )}

        {busy && (
          <div className="flex items-center space-x-2 text-xs text-text-muted">
            <div className="h-2 w-2 rounded-full bg-accent animate-pulse" />
            <span>Working...</span>
          </div>
        )}
      </div>

      {/* Input Form */}
      <form
        className="flex items-center gap-2 border-t border-border bg-surface p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <button
          type="button"
          onClick={toggleVoice}
          aria-label={listening ? 'Stop voice input' : 'Start voice input'}
          className={`rounded-sm p-2.5 transition min-h-[44px] min-w-[44px] flex items-center justify-center ${
            listening
              ? 'animate-pulse bg-danger text-white'
              : 'bg-surface-raised text-text-muted hover:text-text-primary hover:bg-surface-raised/80'
          }`}
        >
          {listening ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
        </button>

        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={2000}
          aria-label="Message"
          placeholder={placeholderText}
          disabled={busy}
          className="flex-1 rounded-sm border border-border bg-surface px-3.5 py-2.5 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none min-h-[44px] disabled:opacity-50"
        />

        <button
          type="submit"
          disabled={busy || !input.trim()}
          aria-label="Send"
          className="rounded-sm bg-accent hover:bg-accent-hover p-2.5 text-white shadow-sm transition disabled:opacity-50 min-h-[44px] min-w-[44px] flex items-center justify-center"
        >
          <Send className="h-5 w-5" />
        </button>
      </form>
    </div>
  );
};
