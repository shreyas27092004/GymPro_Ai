# Phase P12: Frontend

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
All routes in 10.1, three consoles, onboarding wizard, Coach drawer with confirmation card, bundle card and voice, privacy screen, accessible chat, light and dark themes

## Gate (must pass before you stop)
`npm run build`, `npm test`, and the demo script in 1.5 completed manually against Mailpit

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P13.

---

# Spec sections for this phase (copied from the full spec)

## 10. React frontend reference

### 10.1 Screens and routes

| Route | Role | Screen |
| :--- | :--- | :--- |
| `/register` | Public | Account type (User, Trainer, Admin), form, terms. Trainer adds specializations, certifications, bio |
| `/verify?token=` | Public | Verification result and next step (login, waiting for approval, waiting for admin code) |
| `/login` | Public | Email and password only. Shows pending states and the **code box** for admin sign-ups (after a correct password) |
| `/forgot`, `/reset?token=` | Public | Request and set a new password |
| `/onboarding` | USER | Intake wizard, section by section, with the separate health-data consent step |
| `/app` | USER | Dashboard: trial or plan card, upcoming classes, steps and calories, class calendar, nutrition and workout cards with "Based on" |
| `/app/membership` | USER | Plans, usage, upgrade (price preview, then Razorpay Checkout, section 10.4) |
| `/app/privacy` | USER | "What the AI remembers", consent toggle, export and delete my data |
| `/trainer` | TRAINER | Console: calendar, availability editor, series creator, roster, restrictions, feedback summary |
| `/admin` | ADMIN | Overview KPIs, **Approvals** (trainer queue with badge, pending admin requests with reject or revoke, new-admin status), issue triage, staff, broadcasts, security log |
| Coach drawer | All roles | Text and voice, confirmation card, bundle card |

Role-based routing uses the role returned by `GET /api/me` (read from the database), never the token payload. The server enforces everything again; hiding a route is cosmetic.

```tsx
// RequireRole.tsx
import { Navigate, Outlet } from 'react-router-dom';
import { useMe } from './useMe';

export const RequireRole = ({ roles }: { roles: Array<'USER' | 'TRAINER' | 'ADMIN'> }) => {
  const { me, isLoading } = useMe();                       // GET /api/me, refreshes with the refresh cookie on 401
  if (isLoading) return null;
  if (!me) return <Navigate to="/login" replace />;
  if (me.account_status !== 'ACTIVE') return <Navigate to="/login" replace />;
  return roles.includes(me.role) ? <Outlet /> : <Navigate to={homeFor(me.role)} replace />;
};
```

### 10.2 AI Coach with confirmation cards, bundle card and voice

Key points: the client never sends `user_id` or bundle steps; bundle steps are rendered from the server card; voice only fills the input and sends text (it never confirms); text-to-speech reads the reply text only; inputs are disabled while a request is in flight; basic accessibility.

```tsx
// GymProCoach.tsx
import React, { useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Mic, MicOff, Send, ShieldCheck, Volume2, VolumeX } from 'lucide-react';
import axios from 'axios';

type QuickAction =
  | { type: 'CONFIRM'; action_id: string; label: string }
  | { type: 'CONFIRM_BUNDLE'; bundle_id: string; label: string }
  | { type: 'PROMPT'; label: string };
type BundleStep = { step_no: number; type: string; summary: string; depends_on: number[]; conditional_note?: string; result?: string };
type Bundle = { bundle_id: string; headline: string; expires_at: string; steps: BundleStep[]; questions: { agent: string; text: string }[] };
type Msg = { id: string; sender: 'user' | 'agent'; text: string; actions?: QuickAction[]; bundle?: Bundle | null };

const api = (token: string) => axios.create({ baseURL: '/api', headers: { Authorization: `Bearer ${token}` } });

export const GymProCoach: React.FC<{ token: string; conversationId: string }> = ({ token, conversationId }) => {
  const [messages, setMessages] = useState<Msg[]>([
    { id: 'hello', sender: 'agent', text: 'Hi! I can help with classes, trainers, workouts, wellness, nutrition, your membership and problem reports.' },
  ]);
  const [input, setInput] = useState('');
  const [listening, setListening] = useState(false);
  const [speak, setSpeak] = useState(false);
  const recRef = useRef<any>(null);
  const client = api(token);

  const push = (m: Omit<Msg, 'id'>) => {
    const msg = { ...m, id: crypto.randomUUID() };
    setMessages((p) => [...p, msg]);
    if (speak && m.sender === 'agent' && 'speechSynthesis' in window) {
      speechSynthesis.cancel();
      speechSynthesis.speak(new SpeechSynthesisUtterance(m.text));      // reply text only; never ids or action labels
    }
  };

  const chat = useMutation({
    mutationFn: async (message: string) =>
      (await client.post('/agent/chat', { message, conversation_id: conversationId, input_mode: listening ? 'voice' : 'text' })).data,
    onSuccess: (d) => push({ sender: 'agent', text: d.reply, actions: d.quick_actions, bundle: d.bundle?.steps ? d.bundle : null }),
    onError: () => push({ sender: 'agent', text: 'Something went wrong on my side. Please try again in a moment.' }),
  });

  const confirmAction = useMutation({
    mutationFn: async (actionId: string) => (await client.post(`/actions/${actionId}/confirm`)).data,
    onSuccess: (r, actionId) => {
      setMessages((p) => p.map((m) => ({ ...m, actions: m.actions?.filter((a) => a.type !== 'CONFIRM' || a.action_id !== actionId) })));
      push({ sender: 'agent', text: r.ok ? 'Done. It is confirmed.' : `That could not be completed (${r.error}). Want me to find alternatives?` });
    },
    onError: (e: any) => push({ sender: 'agent', text: friendlyError(e) }),
  });

  const confirmBundle = useMutation({
    mutationFn: async (bundleId: string) => (await client.post(`/bundles/${bundleId}/confirm`)).data,
    onSuccess: (r, bundleId) => {
      setMessages((p) => p.map((m) => m.bundle?.bundle_id === bundleId
        ? { ...m, actions: [], bundle: { ...m.bundle!, steps: m.bundle!.steps.map((s) => ({ ...s, result: r.steps.find((x: any) => x.step_no === s.step_no)?.status })) } }
        : m));
      const failed = r.steps.filter((s: any) => s.status !== 'EXECUTED');
      push({ sender: 'agent', text: failed.length === 0 ? 'All steps are done.' :
        `Some steps did not complete: ${failed.map((s: any) => `step ${s.step_no} ${s.status.toLowerCase()}`).join(', ')}. The others went through.` });
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

  const toggleVoice = () => {                                           // speech to text only; confirming is tap-only
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return push({ sender: 'agent', text: 'Voice input is not supported in this browser.' });
    if (listening) { recRef.current?.stop(); return; }
    const rec = new SR();
    rec.lang = navigator.language || 'en-US';
    rec.interimResults = false;
    rec.onresult = (e: any) => send(e.results[0][0].transcript);         // uses the argument, not stale state
    rec.onend = rec.onerror = () => setListening(false);
    recRef.current = rec; rec.start(); setListening(true);
  };

  const busy = chat.isPending || confirmAction.isPending || confirmBundle.isPending;

  return (
    <section className="flex h-screen flex-col bg-slate-50" aria-label="AI fitness coach">
      <header className="flex items-center justify-between border-b bg-white p-4">
        <div>
          <h1 className="text-lg font-bold text-slate-800">AI Fitness Concierge</h1>
          <p className="flex items-center gap-1 text-xs text-slate-500">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" /> I never change anything until you tap Confirm. Voice never confirms.
          </p>
        </div>
        <button onClick={() => setSpeak((s) => !s)} aria-label={speak ? 'Turn off spoken replies' : 'Turn on spoken replies'}
          className="rounded-full bg-slate-100 p-2 text-slate-600">{speak ? <Volume2 className="h-5 w-5" /> : <VolumeX className="h-5 w-5" />}</button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-4" role="log" aria-live="polite">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-xl whitespace-pre-line rounded-2xl p-3 text-sm ${m.sender === 'user' ? 'bg-emerald-600 text-white' : 'border bg-white text-slate-800'}`}>
              {m.text}
              {m.bundle && (
                <ol className="mt-3 space-y-2 rounded-xl border bg-slate-50 p-3 text-xs" aria-label={m.bundle.headline}>
                  <li className="font-semibold text-slate-700">{m.bundle.headline}</li>
                  {m.bundle.steps.map((s) => (
                    <li key={s.step_no} className="flex gap-2">
                      <span className="font-bold">{s.step_no}.</span>
                      <span>{s.summary}{s.depends_on.length > 0 && <em className="block text-slate-500">Goes ahead only if step {s.depends_on.join(', ')} succeeds</em>}
                        {s.result && <strong className="block">{s.result}</strong>}</span>
                    </li>
                  ))}
                  {m.bundle.questions.map((q, i) => <li key={i} className="text-slate-600">Question: {q.text}</li>)}
                </ol>
              )}
              {m.actions?.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {m.actions.map((a, i) =>
                    a.type === 'CONFIRM' ? (
                      <button key={i} disabled={busy} onClick={() => confirmAction.mutate(a.action_id)}
                        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">Confirm: {a.label}</button>
                    ) : a.type === 'CONFIRM_BUNDLE' ? (
                      <button key={i} disabled={busy} onClick={() => confirmBundle.mutate(a.bundle_id)}
                        className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{a.label}</button>
                    ) : (
                      <button key={i} onClick={() => send(a.label)} className="rounded-lg border px-3 py-1.5 text-xs">{a.label}</button>
                    ))}
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {busy && <p className="text-xs text-slate-400">Working...</p>}
      </div>

      <form className="flex items-center gap-2 border-t bg-white p-3" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <button type="button" onClick={toggleVoice} aria-label={listening ? 'Stop voice input' : 'Start voice input'}
          className={`rounded-full p-3 ${listening ? 'animate-pulse bg-red-500 text-white' : 'bg-slate-100 text-slate-600'}`}>
          {listening ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
        </button>
        <input value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000} aria-label="Message"
          placeholder="Try: Book tomorrow evening yoga" disabled={busy}
          className="flex-1 rounded-xl border px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500" />
        <button type="submit" disabled={busy} aria-label="Send" className="rounded-xl bg-emerald-600 p-3 text-white disabled:opacity-50"><Send className="h-5 w-5" /></button>
      </form>
    </section>
  );
};

function friendlyError(e: any): string {
  const code = e?.response?.data?.detail?.error ?? e?.response?.data?.detail ?? e?.response?.data?.error;
  return code === 'ACTION_EXPIRED' ? 'That confirmation expired. Ask me again and I will set it up.'
    : code === 'CLASS_FULL' ? 'That class just filled up. Want me to add you to the waitlist?'
    : code === 'PRICE_CHANGED' ? 'The price changed since I showed it. Ask me again to see the new price.'
    : `That could not be completed (${typeof code === 'string' ? code : 'unknown error'}). Want me to find alternatives?`;
}
```

**Placeholders per role** (shown in the input): USER "Try: Book tomorrow evening yoga", TRAINER "Try: Schedule HIIT Mon/Wed/Fri 6 PM for 4 weeks", ADMIN "Try: Which classes are under 40% full?".

### 10.3 Console features by role

| Console | Components |
| :--- | :--- |
| USER | Trial or plan card with remaining classes, class calendar with injury-aware filter, workout and nutrition cards ("Based on"), notifications bell (SSE), report-a-problem entry, feedback after each class, privacy screen |
| TRAINER | Weekly availability grid, time-off form, series creator with **preview list and conflict flags**, restrictions editor, roster with first names and attendance buttons, feedback summary |
| ADMIN | KPI cards, **Approvals** (trainer queue with live badge; pending admin requests with reject or revoke; new-admin cooling-off status with suspend), issue triage board (severity sorted), staff and trainer verification, broadcast composer with audience count and preview, daily digest history, security log |

### 10.4 Payment step (Razorpay Checkout)

When a confirm call returns `status: AWAITING_PAYMENT`, the UI opens Razorpay Checkout using the `payment` object from the server. The browser receives only the public key id, the order id and the amount; it never sees the key secret. After a successful payment the browser sends the three values Razorpay returns to `POST /api/payments/razorpay/verify`, and the server decides everything.

```tsx
// src/payments/openCheckout.ts
declare global { interface Window { Razorpay: any } }

export type Checkout = { payment_id: string; key_id: string; order_id: string; amount_minor: number;
                         currency: string; description: string; expires_at: string };

const loadCheckout = () => new Promise<void>((resolve, reject) => {
  if (window.Razorpay) return resolve();
  const s = document.createElement('script');
  s.src = 'https://checkout.razorpay.com/v1/checkout.js';
  s.onload = () => resolve(); s.onerror = () => reject(new Error('CHECKOUT_LOAD_FAILED'));
  document.body.appendChild(s);
});

/** Resolves with the server's verify response, or 'DISMISSED' when the user closes the window. */
export async function openCheckout(c: Checkout, me: { name: string; email: string }) {
  await loadCheckout();
  return new Promise<any>((resolve) => {
    const rzp = new window.Razorpay({
      key: c.key_id, order_id: c.order_id, amount: c.amount_minor, currency: c.currency,
      name: 'GymPro', description: c.description, prefill: { name: me.name, email: me.email },
      handler: async (resp: { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string }) =>
        resolve((await client.post('/payments/razorpay/verify', resp)).data),
      modal: { ondismiss: () => resolve('DISMISSED'), escape: false },
    });
    rzp.open();
  });
}
```

Behavior rules:

- In `confirmBundle.onSuccess` and `confirmAction.onSuccess`, check `r.status === 'AWAITING_PAYMENT'` first: mark the step "Waiting for payment", call `openCheckout(r.payment, me)`, then merge the returned step results into the card exactly as for a normal confirm.
- If the result is `'DISMISSED'`, keep the card in a **Pay now** state. Pressing it calls `GET /payments/{id}` and reopens Checkout while the order is still valid. Offer **Cancel payment**, which calls `POST /payments/{id}/cancel`; the server then skips the dependent steps.
- If the browser closes or the network drops after paying, the webhook or the reconciler still completes the payment. On the next load the Coach and `/app/membership` show the real state from `GET /api/me/membership` and `GET /payments/{id}`.
- Show the amount as the server formats it (currency and minor units come from the server). Never compute prices in the client.
- `/app/membership` uses the same `openCheckout` for a direct upgrade, after a price preview that comes from the same `price_diff` quote.
- Voice never starts or confirms a payment. Paying is always a deliberate tap in the Checkout window.
- Content Security Policy must allow `https://checkout.razorpay.com` for scripts and frames, and `https://api.razorpay.com` is **not** called from the browser.

---

### 4.7 Voice interface rules

| Rule | Detail |
| :--- | :--- |
| Input | Browser speech recognition to text, then the same `/agent/chat` endpoint as typed text |
| Output | Optional text-to-speech of the reply text only (never reads action ids). Off by default |
| Confirmation | Tap only. The phrase "yes, confirm" spoken or typed is never execution |
| Storage | No audio stored by default |
| Languages | English first. Hindi and Kannada are a later phase (section 18) |
| Privacy | Health details are not spoken aloud when the device is flagged as shared; the UI shows them as text only |

---

### 4.9 Trainer experience

| Need | Feature |
| :--- | :--- |
| Set working days | Weekly availability (days, hours) and time off |
| Set restrictions | Per class: capacity, minimum level, minimum age, allowed plans, trial eligibility, contraindicated injuries, booking cut-off, late-cancel window, equipment |
| Schedule fast | "Schedule HIIT Mon/Wed/Fri 6 PM for 4 weeks, cap 12, beginners, no knee issues" produces a preview list of sessions with conflicts flagged, then one confirmation |
| Run the class | Roster, attendance, notes, aggregated member feedback summary |
| Stay safe | System refuses sessions outside availability, overlapping sessions, and changes that would break existing bookings without notifying members |

**Recurring series behavior**
- A series is a `class_series` row plus generated `fitness_classes` instances.
- Preview lists every instance with a status: `OK`, `CONFLICT_TRAINER_OVERLAP`, `OUTSIDE_AVAILABILITY`, `TIME_OFF`, `PAST`.
- On confirm, only `OK` instances are created. Skipped instances are reported back.
- Changing or cancelling a series asks whether it applies to one instance or all future instances. Members with bookings are notified through the outbox (`class.cancelled`).

---

### 4.10 Admin experience

| Need | Feature |
| :--- | :--- |
| Overview | KPIs: active members, trials started and converted, MRR, occupancy, no-show rate, churn risk, open issues, trainer ratings |
| Approvals | **New trainer requests** queue with badge (approve, reject with reason, ask for more information); **pending admin requests** list with reject or revoke; new-admin cooling-off status |
| Agent help | Plain language ("Which classes are under 40% full?"). ADMIN_INSIGHTS answers from the metric catalog only |
| Daily digest | AI-written summary emailed each morning. **Numbers come from tools, not the model** |
| Issue triage | New user reports are summarized, categorized and given a severity. Admin picks the action (contact user, warn trainer, escalate) |
| Staff management | Invite and verify trainers, grant memberships, cancel classes |
| Broadcasts | Draft announcement with AI, preview audience, confirm. Non-essential emails honor unsubscribe |
| Security log | New admins, approvals, failed codes, suspensions |

All admin actions use the same propose, confirm, audit pattern.

---

## 17. REST API catalog

All endpoints are under `/api`. "Active" means the caller has `account_status = ACTIVE`. Public endpoints are rate limited per IP and per email.

| Method and path | Role | Purpose |
| :--- | :--- | :--- |
| `POST /auth/register` | Public | Create account (USER, TRAINER or ADMIN request). Same response whether or not the email exists |
| `POST /auth/verify-email` | Public | Consume the verification token; moves the account to its next state |
| `POST /auth/login` | Public | Email and password only; returns access token, sets refresh cookie |
| `POST /auth/activate-admin` | Public | Email, password and one-time code for admin sign-ups |
| `POST /auth/refresh` | Public (cookie) | Rotate refresh token |
| `POST /auth/logout` | Active | Revoke the refresh family |
| `POST /auth/forgot-password`, `POST /auth/reset-password` | Public | Reset flow; all sessions revoked on success |
| `GET /me` | Active | Role, status, plan, consent flags, cooling-off flag |
| `GET/PUT /me/intake`, `POST /me/consent`, `DELETE /me/consent` | USER | Intake sections, health-data consent and withdrawal |
| `GET /me/memory`, `POST /me/export`, `DELETE /me/data` | USER | What the AI remembers, export, delete |
| `GET /plans`, `GET /trainers`, `GET /classes` | Active | Browse catalog (trainers show verified credentials only) |
| `GET /me/bookings`, `GET /me/membership`, `GET /me/trial` | USER | Own data |
| `POST /agent/chat` | Active | Text or voice transcript to the agent pipeline |
| `POST /actions/{id}/confirm` | Active (owner) | Execute one proposed action |
| `POST /bundles/{id}/confirm` | Active (owner) | Execute a bundle in order; may return `AWAITING_PAYMENT` with a checkout object |
| `POST /payments/razorpay/verify` | USER (owner of the order) | Verify the Checkout signature and finalize the payment |
| `GET /payments/{id}`, `POST /payments/{id}/cancel` | USER (owner) | Payment status and reopen data; abandon an unpaid order |
| `POST /payments/razorpay/webhook` | Public (HMAC signature only) | Razorpay events: captured, failed, refund processed. Deduplicated by event id |
| `GET /admin/payments?status=NEEDS_REVIEW` | ADMIN | Review queue for late or inconsistent payments |
| `POST /feedback` | USER | Class, trainer or answer feedback |
| `GET /notifications`, `POST /notifications/{id}/read`, `GET /notifications/stream` | Active | In-app notices and SSE stream |
| `GET/PUT /trainer/availability`, `POST /trainer/time-off` | TRAINER | Own availability |
| `GET /trainer/classes`, `GET /trainer/classes/{id}/roster`, `POST /trainer/classes/{id}/attendance` | TRAINER | Own classes, first-name rosters, attendance |
| `POST /trainer/series/preview` | TRAINER | Preview recurring series |
| `GET /admin/overview`, `GET /admin/metrics/{name}` | ADMIN | KPIs and catalog metrics |
| `GET /admin/trainer-requests`, `POST /admin/trainer-requests/{id}/decision` | ADMIN (not in cooling-off for decisions) | Queue and decisions (approve, reject with reason, ask for more information) |
| `GET /admin/admin-requests`, `POST /admin/admin-requests/{id}/reject`, `POST /admin/users/{id}/suspend` | ADMIN | Reject or revoke admin requests; suspend new admins. **No approve endpoint exists** |
| `GET /admin/issues`, `PATCH /admin/issues/{id}` | ADMIN | Triage |
| `POST /admin/staff/invites`, `POST /admin/broadcasts/preview`, `POST /admin/broadcasts` | ADMIN (not in cooling-off) | Invites and announcements (broadcast sending goes through confirm) |
| `GET /admin/security-log` | ADMIN | New admins, approvals, failed codes, suspensions |
| `GET /health`, `GET /ready` | Public | Liveness and readiness (DB, RabbitMQ, LLM) |

**Error code catalog (stable strings returned in `detail.error`)**

| Code | Meaning |
| :--- | :--- |
| `INVALID_CREDENTIALS`, `TRY_LATER` | Wrong login, lockout |
| `EMAIL_NOT_VERIFIED`, `ACCOUNT_PENDING_APPROVAL`, `ACCOUNT_PENDING_ADMIN_CODE`, `ACCOUNT_REJECTED`, `ACCOUNT_EXPIRED`, `ACCOUNT_SUSPENDED` | Account state after a correct password |
| `INVALID_OR_EXPIRED_TOKEN`, `INVALID_CODE`, `CODE_EXPIRED`, `REQUEST_LOCKED` | Token and code problems |
| `ADMIN_SIGNUP_UNAVAILABLE`, `TOO_MANY_PENDING_ADMIN_REQUESTS`, `ONE_REQUEST_PER_DAY` | Admin sign-up limits |
| `ACTION_EXPIRED`, `PRICE_CHANGED`, `CLASS_FULL`, `CONFLICT`, `NO_ENTITLEMENT`, `RULE_FAILED`, `ALREADY_BOOKED`, `CLASS_UNAVAILABLE` | Executor business errors |
| `DEPENDENCY_FAILED` | Bundle step skipped |
| `PAYMENT_PROVIDER_REQUIRED` | Payments disabled, or `mock` in production |
| `PAYMENT_SIGNATURE_INVALID`, `PAYMENT_FAILED`, `PAYMENT_EXPIRED`, `PAYMENT_CANCELLED`, `PAYMENT_NEEDS_REVIEW` | Payment outcomes |
| `REPORT_LIMIT_REACHED`, `EMAIL_CAP_REACHED` | Daily caps |
| `COOLING_OFF_ACTIVE`, `FORBIDDEN`, `CONSENT_REQUIRED`, `TOOL_NOT_ALLOWED` | Authorization |
