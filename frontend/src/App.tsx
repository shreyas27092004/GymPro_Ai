import { Activity, Dumbbell, ShieldCheck, Zap } from 'lucide-react'

export function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Dumbbell className="w-8 h-8 text-emerald-400" />
          <h1 className="text-xl font-bold tracking-tight text-white">
            GymPro <span className="text-emerald-400">AI</span>
          </h1>
        </div>
        <div className="flex items-center space-x-2 text-xs font-mono bg-slate-800/80 px-3 py-1.5 rounded-full border border-slate-700">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span className="text-slate-300">Phase P0: Scaffold Ready</span>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto p-6 md:p-12 flex flex-col justify-center">
        <div className="text-center space-y-4 mb-12">
          <h2 className="text-4xl md:text-5xl font-extrabold tracking-tight text-white">
            Enterprise Autonomous Gym Operations
          </h2>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto">
            Multi-agent architecture with deterministic execution, strict human-in-the-loop safety boundaries, and role-based consoles.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6">
          <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition">
            <div className="w-12 h-12 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400 mb-4">
              <Zap className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">Member AI Coach</h3>
            <p className="text-sm text-slate-400">
              Goal-oriented conversational coach with deterministic calculators for BMR, macros, and workout scheduling.
            </p>
          </div>

          <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition">
            <div className="w-12 h-12 rounded-lg bg-blue-500/10 flex items-center justify-center text-blue-400 mb-4">
              <Activity className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">Trainer Ops</h3>
            <p className="text-sm text-slate-400">
              Copilot for trainer availability, roster management, and class scheduling with RLS privacy protection.
            </p>
          </div>

          <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 hover:border-slate-700 transition">
            <div className="w-12 h-12 rounded-lg bg-purple-500/10 flex items-center justify-center text-purple-400 mb-4">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">Admin Governance</h3>
            <p className="text-sm text-slate-400">
              Metric catalog analytics with k-anonymity floors, staff approvals, and secure outbox notification bus.
            </p>
          </div>
        </div>
      </main>

      <footer className="border-t border-slate-800 py-4 text-center text-xs text-slate-500">
        GymPro AI &copy; 2026. Built with FastAPI, LangGraph, PostgreSQL, and React.
      </footer>
    </div>
  )
}

export default App
