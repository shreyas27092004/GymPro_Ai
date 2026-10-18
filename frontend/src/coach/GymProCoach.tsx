// src/coach/GymProCoach.tsx
import React, { useRef, useState } from 'react';
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
} from 'lucide-react';
import { client, friendlyError } from '../api/client';
import { openCheckout } from '../payments/openCheckout';
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
        push({ sender: 'agent', text: 'Waiting for payment confirmation. Opening secure checkout...' });
        const payRes = await openCheckout(r.payment, {
          name: me?.full_name || 'Member',
          email: me?.email_masked || 'member@gympro.test',
        });
        if (payRes === 'DISMISSED') {
          push({ sender: 'agent', text: 'Payment was dismissed. You can reopen checkout from your Membership page.' });
        } else if (payRes.ok) {
          push({ sender: 'agent', text: 'Payment successful! Your membership is active.' });
        } else {
          push({ sender: 'agent', text: `Payment could not be completed (${payRes.error || 'Failed'}).` });
        }
        return;
      }

      push({
        sender: 'agent',
        text: r.ok ? 'Done. It is confirmed.' : `That could not be completed (${r.error}). Want me to find alternatives?`,
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
        push({ sender: 'agent', text: 'Waiting for payment confirmation. Opening secure checkout...' });
        const payRes = await openCheckout(r.payment, {
          name: me?.full_name || 'Member',
          email: me?.email_masked || 'member@gympro.test',
        });
        if (payRes === 'DISMISSED') {
          push({ sender: 'agent', text: 'Payment was dismissed. You can reopen checkout from your Membership page.' });
        } else if (payRes.ok) {
          push({ sender: 'agent', text: 'Payment received! Your bundle steps have finished executing.' });
        } else {
          push({ sender: 'agent', text: `Payment could not be completed (${payRes.error || 'Failed'}).` });
        }
        return;
      }

      const steps: any[] = r.steps || [];
      const failed = steps.filter((s) => s.status !== 'EXECUTED');
      push({
        sender: 'agent',
        text:
          failed.length === 0
            ? 'All steps are done.'
            : `Some steps did not complete: ${failed
                .map((s) => `step ${s.step_no} ${s.status.toLowerCase()}`)
                .join(', ')}. The others went through.`,
      });
    },
    onError: (e: any) => push({ sender: 'agent', text: friendlyError(e) }),
  });

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
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl transition-transform duration-300"
      role="region"
      aria-label="AI fitness coach"
    >
      {/* Header */}
      <header className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/80 px-4 py-3">
        <div className="flex items-center space-x-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <Bot className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h2 className="text-base font-bold text-slate-900 dark:text-white">AI Fitness Concierge</h2>
              <span className="flex items-center rounded-full bg-emerald-100 dark:bg-emerald-950/60 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:text-emerald-300">
                <Sparkles className="mr-0.5 h-2.5 w-2.5" /> Active
              </span>
            </div>
            <p className="flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
              I never change anything until you tap Confirm. Voice never confirms.
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-1">
          <button
            onClick={() => setSpeak((s) => !s)}
            aria-label={speak ? 'Turn off spoken replies' : 'Turn on spoken replies'}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            {speak ? <Volume2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" /> : <VolumeX className="h-4 w-4" />}
          </button>
          <button
            onClick={onClose}
            aria-label="Close assistant"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* Message List */}
      <div className="flex-1 space-y-4 overflow-y-auto p-4" role="log" aria-live="polite">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[90%] whitespace-pre-line rounded-2xl p-3.5 text-sm shadow-sm ${
                m.sender === 'user'
                  ? 'bg-emerald-600 text-white dark:bg-emerald-600'
                  : 'border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100'
              }`}
            >
              {m.text}

              {/* Bundle Card */}
              {m.bundle && (
                <div
                  className="mt-3 space-y-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/80 p-3 text-xs"
                  aria-label={m.bundle.headline}
                >
                  <div className="font-semibold text-slate-900 dark:text-white border-b border-slate-200 dark:border-slate-700 pb-1.5 flex items-center justify-between">
                    <span>{m.bundle.headline}</span>
                    <span className="text-[10px] text-slate-400 font-normal">
                      Expires in 15m
                    </span>
                  </div>
                  <ol className="space-y-2 pt-1">
                    {m.bundle.steps.map((s) => (
                      <li key={s.step_no} className="flex items-start gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900/50 text-[11px] font-bold text-emerald-800 dark:text-emerald-300">
                          {s.step_no}
                        </span>
                        <div className="flex-1">
                          <p className="font-medium text-slate-800 dark:text-slate-200">{s.summary}</p>
                          {s.depends_on.length > 0 && (
                            <p className="text-[11px] text-slate-500 dark:text-slate-400">
                              Goes ahead only if step {s.depends_on.join(', ')} succeeds
                            </p>
                          )}
                          {s.result && (
                            <span
                              className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                                s.result === 'EXECUTED'
                                  ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                                  : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
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
                    <div className="mt-2 border-t border-slate-200 dark:border-slate-700 pt-2 space-y-1">
                      {m.bundle.questions.map((q, i) => (
                        <p key={i} className="text-[11px] text-slate-600 dark:text-slate-400 italic">
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
                        className="rounded-lg bg-emerald-600 hover:bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50"
                      >
                        Confirm: {a.label}
                      </button>
                    ) : a.type === 'CONFIRM_BUNDLE' ? (
                      <button
                        key={i}
                        disabled={busy}
                        onClick={() => confirmBundle.mutate(a.bundle_id)}
                        className="rounded-lg bg-emerald-600 hover:bg-emerald-700 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition disabled:opacity-50"
                      >
                        Confirm: {a.label}
                      </button>
                    ) : (
                      <button
                        key={i}
                        disabled={busy}
                        onClick={() => send(a.label)}
                        className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition"
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

        {busy && (
          <div className="flex items-center space-x-2 text-xs text-slate-500 dark:text-slate-400">
            <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>Working...</span>
          </div>
        )}
      </div>

      {/* Input Form */}
      <form
        className="flex items-center gap-2 border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <button
          type="button"
          onClick={toggleVoice}
          aria-label={listening ? 'Stop voice input' : 'Start voice input'}
          className={`rounded-full p-2.5 transition ${
            listening
              ? 'animate-pulse bg-red-500 text-white'
              : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
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
          className="flex-1 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3.5 py-2.5 text-sm text-slate-900 dark:text-white placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
        />

        <button
          type="submit"
          disabled={busy || !input.trim()}
          aria-label="Send"
          className="rounded-xl bg-emerald-600 hover:bg-emerald-700 p-2.5 text-white shadow-sm transition disabled:opacity-50"
        >
          <Send className="h-5 w-5" />
        </button>
      </form>
    </div>
  );
};
