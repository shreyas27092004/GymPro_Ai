# GymPro AI Design System & Visual Specification

## 1. Subject & Target Audiences
GymPro AI is an enterprise gym operations and AI fitness platform.
- **Gym Members (Mobile-First):** Need instant clarity on remaining class credits, injury-safe schedules, and fast conversational booking with quick taps.
- **Trainers (Desk & Tablet):** Require an efficient schedule view, roster attendance toggles, and recurring series conflict detection without cognitive overload.
- **Administrators (Desktop):** Require high-density metric catalog analytics, approval queues with clear distinction between approve and revoke, and fast issue triage.

---

## 2. Color System & Semantic Tokens

Our color architecture relies on CSS custom properties mapped directly into Tailwind tokens, enabling seamless light/dark mode transitions without ad hoc utility clashes.

| Token Name | Light Value | Dark Value | Role & Usage |
| :--- | :--- | :--- | :--- |
| `--color-base` | `#F8FAFC` (Slate 50) | `#090D16` (Deep Midnight) | Viewport background |
| `--color-surface` | `#FFFFFF` (Pure White) | `#111827` (Slate 900) | Content cards, tables, inputs |
| `--color-surface-raised`| `#F1F5F9` (Slate 100) | `#1E293B` (Slate 800) | Hover states, pill containers, drawer backdrop |
| `--color-text-primary` | `#0F172A` (Slate 900) | `#F8FAFC` (Slate 50) | High-contrast headings and primary labels |
| `--color-text-muted` | `#64748B` (Slate 500) | `#94A3B8` (Slate 400) | Supporting labels, timestamps, metadata |
| `--color-accent` | `#059669` (Emerald 600) | `#10B981` (Emerald 500) | Primary actions, AI Coach highlight, active states |
| `--color-accent-subtle` | `#D1FAE5` (Emerald 100) | `#064E3B` (Emerald 950) | Active badges, selected highlights |
| `--color-danger` | `#DC2626` (Red 600) | `#EF4444` (Red 500) | Destructive actions, high severity, error alerts |
| `--color-border` | `#E2E8F0` (Slate 200) | `#1E293B` (Slate 800) | Subtle structural dividers and card outlines |

---

## 3. Typography & Hierarchy

- **Font Family:** `Plus Jakarta Sans` (installed via `@fontsource-variable/plus-jakarta-sans`). Geometric clarity with humanist curves; crisp numeral rendering for reps, calories, and times.
- **Font Roles:**
  - **Headings & Metric Numbers:** Bold (700) and ExtraBold (800) for fast scannability.
  - **Body & Prompts:** Medium (500) and Regular (400) with 1.5 line height for comfortable chat reading.
  - **Meta & Badges:** SemiBold (600) uppercase with tracking for status pills and labels.

### Scale:
- `text-xs`: 12px (line-height 16px) — Badges, secondary notes, dependencies
- `text-sm`: 14px (line-height 20px) — Chat body, inputs, button labels
- `text-base`: 16px (line-height 24px) — Card titles, primary text
- `text-xl`: 20px (line-height 28px) — Section headers
- `text-2xl`: 24px (line-height 32px) — View titles
- `text-4xl`: 36px (line-height 40px) — Metric KPIs and hero titles

---

## 4. Spacing, Radii & Depth Hierarchy

Rather than applying an arbitrary uniform border radius to every element, radii are scaled according to component elevation:
- **Small Radii (8px / `rounded-lg`):** Badges, input fields, sub-buttons, table cells.
- **Medium Radii (14px / `rounded-2xl`):** Content cards, workout summaries, schedule cards.
- **Large Radii (20px / `rounded-3xl`):** AI Coach Drawer on desktop, major modals, bundle confirmation cards.
- **Touch Targets:** Minimum 44px × 44px on mobile for all interactive buttons and taps.

---

## 5. Layout Architecture & ASCII Wireframes

### A. Member Home (`/app`)
*Concept: Quick status at a glance with one-tap entry to class booking and conversational AI coach.*
```text
+-------------------------------------------------------------+
| [Logo] GymPro AI               [Sun/Moon] [AI Coach Button] |
+-------------------------------------------------------------+
| Welcome back, Rahul!                                        |
| +-------------------------+ +-----------------------------+ |
| | Current Entitlement     | | Today's Targets             | |
| | Gold Membership: ACTIVE | | [8,420 steps] [520 kcal]    | |
| +-------------------------+ +-----------------------------+ |
| +---------------------------------------------------------+ |
| | Personalized AI Guidance (Based on: Knee Safety)        | |
| | > Recommended: Low-Impact Mobility & Core               | |
| +---------------------------------------------------------+ |
| +---------------------------------------------------------+ |
| | Upcoming Classes                         [Cancel Class] | |
| | HIIT Power - Tomorrow 6:00 PM                           | |
| +---------------------------------------------------------+ |
+-------------------------------------------------------------+
```

### B. Class Schedule (`/app` Catalog)
*Concept: High-density schedule grid featuring instant injury-contraindication filters.*
```text
+-------------------------------------------------------------+
| Filter: [All] [HIIT] [Yoga] [Strength]                      |
| +--------------------+ +--------------------+                |
| | Yoga Flow (Low)    | | HIIT Circuit       |                |
| | 7:00 AM - Asha Rao | | 6:00 PM - Vikram   |                |
| | [Knee Safe]        | | [!] High Impact    |                |
| | [Book with AI]     | | [Book with AI]     |                |
| +--------------------+ +--------------------+                |
+-------------------------------------------------------------+
```

### C. Coach Drawer & Confirmation / Bundle Card (Hero Element)
*Concept: The centerpiece of GymPro — conversational clarity culminating in structured, multi-step action bundles.*
```text
+-------------------------------------------------------------+
| AI Fitness Concierge                          [Vol] [Close] |
| [ShieldCheck] Tap Confirm to execute. Voice never confirms. |
+-------------------------------------------------------------+
| User: Upgrade to Gold and book tomorrow 6 PM HIIT           |
|                                                             |
| Coach: I have prepared your plan upgrade and class booking. |
| +---------------------------------------------------------+ |
| | ACTION BUNDLE: Plan Upgrade & Booking                   | |
| | 1. Change membership to Gold (₹1,999/mo)                | |
| | 2. Book HIIT Circuit (Depends on step 1)                | |
| | 3. Send calendar invite to rahul@example.com            | |
| | [Confirm: Upgrade & Book (₹1,999)]                      | |
| +---------------------------------------------------------+ |
|                                                             |
| [Mic] [Type: Book tomorrow evening yoga...       ] [Send]   |
+-------------------------------------------------------------+
```

### D. Trainer Console (`/trainer`)
*Concept: Compact command deck for schedule generation, roster attendance, and conflict avoidance.*
```text
+-------------------------------------------------------------+
| [Rosters & Attendance]  [Series Creator]  [Availability]    |
| +---------------------------------------------------------+ |
| | Roster: HIIT Power (Tomorrow 6:00 PM)                   | |
| | 1. John D. [Present] [No-Show] (First name only)        | |
| | 2. Priya M. [Present] [No-Show]                         | |
| +---------------------------------------------------------+ |
| Recurring Series Preview:                                   |
| - Week 1 (Oct 19): [OK]                                    |
| - Week 2 (Oct 26): [CONFLICT_TRAINER_OVERLAP]              |
+-------------------------------------------------------------+
```

### E. Admin Governance (`/admin`)
*Concept: High-clarity operational dashboard enforcing k-anonymity and privilege escalation guards.*
```text
+-------------------------------------------------------------+
| [Overview KPIs]  [Approvals (3)]  [Issue Triage]  [Staff]   |
| [MRR: ₹284k]  [Occupancy: 68%]  [Conversion: 74%]           |
| +---------------------------------------------------------+ |
| | Trainer Requests Queue                   [Badge: 3]     | |
| | Rahul Sharma (CSCS, Strength)      [Approve] [Reject]   | |
| +---------------------------------------------------------+ |
| | Pending Admin Requests (HMAC Code Verification)         | |
| | Priya K. (Requested Oct 16)        [Reject / Revoke]    | |
| | *No Approve button exists (One-time code flow only)*    | |
| +---------------------------------------------------------+ |
+-------------------------------------------------------------+
```

---

## 6. Deliberate Design Decisions vs Generic Defaults

1. **Memorable Element Hierarchy (Spend Boldness in One Place):** Rather than cluttering the app with neon gym gradients, the consoles maintain clean, calm, professional slate surfaces. The **AI Coach Drawer and the Action Bundle Card** are given the signature emerald focus, glowing status rings, and structured step cards.
2. **First-Name Only Roster Display:** Instead of standard data tables with full user rows, attendee tables explicitly display first names only with privacy badges, enforcing GDPR and spec rules visually.
3. **Admin Escalation Visual Defense:** The admin interface makes it physically impossible to approve an admin request by deliberately providing only `Reject / Revoke` controls, accompanied by an explicit security policy notice.
4. **Motion with Intent:** Subtle slide-overs for the coach drawer and smooth height transitions for bundle execution results. When `prefers-reduced-motion` is enabled, all animations degrade instantly to non-animated opacity states.
