# GymPro AI: prompt pack (run order)

Put this folder in the repo as `prompts/` and the full spec as `docs/GYMPRO_SPEC.md`.

Run **one file at a time** in Antigravity, in the order below. Do not start the next file until the gate of the current one passes and it is committed.

Paste this for each phase (replace the file name):

```text
Read prompts/00_CORE.md, then prompts/<FILE>. Write a short plan and task list, implement the whole phase with its tests,
run the gate exactly as written (fix code, never the safety tests), update README.md and docs/PROGRESS.md, commit, and stop.
Do not start the next phase.
```

| Order | File | Goal | Size |
| :-- | :-- | :-- | :-- |
| 0 | `00_CORE.md` | Rules, decisions, architecture (read every time) | |
| 1 | `P0_scaffold.md` | Scaffold and environment | 10 KB |
| 2 | `P1_database.md` | Database | 41 KB |
| 3 | `P2_auth.md` | Auth service | 27 KB |
| 4 | `P3_messaging.md` | Messaging | 14 KB |
| 5 | `P4_role_requests.md` | Role requests | 20 KB |
| 6 | `P5_trial_entitlements.md` | Trial, entitlements, membership | 13 KB |
| 7 | `P6_executors.md` | Executors | 25 KB |
| 8 | `P6b_payments.md` | Payments (Razorpay) | 44 KB |
| 9 | `P7_tool_layer.md` | Tool layer | 14 KB |
| 10 | `P8_agent_runner.md` | Agent runner and first four agents | 44 KB |
| 11 | `P9_supervisor.md` | Supervisor | 29 KB |
| 12 | `P10_remaining_agents_kb.md` | Remaining user agents and knowledge base | 19 KB |
| 13 | `P11_staff_copilots.md` | Staff copilots | 22 KB |
| 14 | `P12_frontend.md` | Frontend | 24 KB |
| 14b | `P12b_design_polish.md` | Visual design and motion polish (optional, after P12) | 3 KB |
| 15 | `P13_hardening.md` | Hardening and release | 12 KB |
| 16 | `P14_company_pc_migration.md` | Move to a company PC through GitHub | 17 KB |

Core size: 18 KB.
