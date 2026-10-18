# Phase P12b: Visual design and motion polish

**Before you start:** read `prompts/00_CORE.md`. P12 must already pass its gate and be committed. This phase changes how the app looks and feels only. It must not change behavior, routes, API calls, or any security or safety logic.

## Task
Make the frontend look like a modern, professionally designed product, not a default admin template. Work in two passes.

**Pass 1: design plan (write it to `docs/DESIGN.md` before any code).**
- Subject: a gym platform with an AI coach. Audiences: members (mobile first, quick actions), trainers (schedule and rosters), admins (queues and metrics).
- Color: 4 to 6 named hex values (base, surface, text, one brand accent, success, danger) with light and dark variants, as CSS variables mapped into the Tailwind theme.
- Type: one or two typefaces with clear roles and a defined type scale. Install them as npm packages (for example `@fontsource-variable/...`) so no external font CDN is needed.
- Layout: one-sentence concept per area (member home, class schedule, Coach drawer, trainer console, admin console) with a small ASCII wireframe for each.
- Principles: spend boldness in one place. Make the **Coach drawer and the confirmation / bundle card** the memorable element. Keep the rest calm and consistent.
- Review the plan against the brief. If any part is a generic default you would use for any app, change it and write one line on what you changed and why.

**Pass 2: implement.**
- Replace ad hoc styles with the tokens. One spacing scale, a small set of radii by hierarchy (not one radius on everything), consistent shadows and borders.
- Real states for every screen: loading skeletons, empty states with a clear next action, error states that say what went wrong and how to fix it.
- Copy: sentence case, active verbs, same action name through the whole flow ("Confirm", then "Confirmed"). No filler, no jargon.
- Motion only where it answers a user action: drawer open and close, confirmation card appearing, step status changing (pending, paid, skipped), toast on success. At most one page-load moment. No entrance animations on every section and no hover effects on every card.
- Respect `prefers-reduced-motion`: every animation has a non-animated fallback.
- Accessibility floor: visible keyboard focus, color contrast AA in light and dark, focus trap and Escape in the drawer and modals, `aria-live` kept on chat, touch targets at least 44px on mobile.
- Responsive from 360px wide up. The Coach drawer is full screen on mobile.
- Do not touch the Razorpay Checkout window; style only the "Waiting for payment", "Pay now" and "Cancel payment" states around it.

## Deliverables
`docs/DESIGN.md` (tokens, type, layout notes), a theme layer (CSS variables plus Tailwind config), shared UI components (Button, Card, Badge, Dialog, Drawer, Toast, Skeleton, EmptyState), restyled screens for all routes in 10.1, and screenshots of key screens (light and dark, mobile and desktop) saved under `docs/screenshots/`.

## Gate (must pass before you stop)
`npm run build` and `npm test` still pass with no test deleted or weakened. Every route renders without console errors at 360px and 1280px in light and dark. No hard-coded colors outside the theme layer (`grep` check). Reduced-motion mode shows no animation. The demo script in 1.5 still completes.

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P13.
