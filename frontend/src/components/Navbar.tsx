// src/components/Navbar.tsx
import React from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import {
  Dumbbell,
  Sun,
  Moon,
  Sparkles,
  LogOut,
  ShieldCheck,
  UserCheck,
  Calendar,
  CreditCard,
  Lock,
} from 'lucide-react';
import { useAuth } from '../auth/AuthContext';

interface NavbarProps {
  onOpenCoach: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenCoach }) => {
  const { me, logout, theme, toggleTheme } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const isActive = (path: string) => location.pathname === path;

  return (
    <nav className="sticky top-0 z-40 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8 h-16">
        {/* Brand */}
        <div className="flex items-center space-x-6">
          <Link to="/" className="flex items-center space-x-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
              <Dumbbell className="h-5 w-5" />
            </div>
            <span className="text-lg font-extrabold tracking-tight text-slate-900 dark:text-white">
              GymPro <span className="text-emerald-600 dark:text-emerald-400">AI</span>
            </span>
          </Link>

          {/* Navigation Links for Authenticated Users */}
          {me && (
            <div className="hidden md:flex items-center space-x-1 text-sm font-medium">
              {me.role === 'USER' && (
                <>
                  <Link
                    to="/app"
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-lg transition ${
                      isActive('/app')
                        ? 'bg-slate-100 dark:bg-slate-800 text-emerald-600 dark:text-emerald-400 font-semibold'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                    }`}
                  >
                    <Calendar className="h-4 w-4" /> Dashboard
                  </Link>
                  <Link
                    to="/app/membership"
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-lg transition ${
                      isActive('/app/membership')
                        ? 'bg-slate-100 dark:bg-slate-800 text-emerald-600 dark:text-emerald-400 font-semibold'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                    }`}
                  >
                    <CreditCard className="h-4 w-4" /> Membership
                  </Link>
                  <Link
                    to="/app/privacy"
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-lg transition ${
                      isActive('/app/privacy')
                        ? 'bg-slate-100 dark:bg-slate-800 text-emerald-600 dark:text-emerald-400 font-semibold'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                    }`}
                  >
                    <Lock className="h-4 w-4" /> Privacy
                  </Link>
                </>
              )}

              {me.role === 'TRAINER' && (
                <Link
                  to="/trainer"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg transition ${
                    isActive('/trainer')
                      ? 'bg-slate-100 dark:bg-slate-800 text-emerald-600 dark:text-emerald-400 font-semibold'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  <UserCheck className="h-4 w-4" /> Trainer Console
                </Link>
              )}

              {me.role === 'ADMIN' && (
                <Link
                  to="/admin"
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg transition ${
                    isActive('/admin')
                      ? 'bg-slate-100 dark:bg-slate-800 text-emerald-600 dark:text-emerald-400 font-semibold'
                      : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                  }`}
                >
                  <ShieldCheck className="h-4 w-4" /> Admin Console
                </Link>
              )}
            </div>
          )}
        </div>

        {/* Right Actions */}
        <div className="flex items-center space-x-3">
          {/* Theme Toggle */}
          <button
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 transition"
          >
            {theme === 'dark' ? <Sun className="h-5 w-5 text-amber-400" /> : <Moon className="h-5 w-5" />}
          </button>

          {/* AI Coach Trigger Button */}
          {me && (
            <button
              onClick={onOpenCoach}
              className="flex items-center gap-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm transition"
              aria-label="Open AI Assistant"
            >
              <Sparkles className="h-4 w-4" />
              <span className="hidden sm:inline">AI Coach</span>
            </button>
          )}

          {/* User Profile / Logout or Public Sign In */}
          {me ? (
            <div className="flex items-center space-x-2 pl-2 border-l border-slate-200 dark:border-slate-800">
              <div className="hidden sm:block text-right">
                <p className="text-xs font-semibold text-slate-900 dark:text-white">{me.full_name}</p>
                <div className="flex items-center justify-end gap-1">
                  <span className="inline-block rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.2 text-[10px] font-mono text-slate-600 dark:text-slate-300">
                    {me.role}
                  </span>
                  {me.cooling_off_active && (
                    <span className="rounded bg-amber-100 dark:bg-amber-950 px-1 py-0.2 text-[9px] font-semibold text-amber-800 dark:text-amber-300">
                      Cooling Off
                    </span>
                  )}
                </div>
              </div>

              <button
                onClick={handleLogout}
                aria-label="Log out"
                className="rounded-lg p-2 text-slate-500 hover:text-red-600 hover:bg-red-50 dark:text-slate-400 dark:hover:bg-red-950/40 transition"
                title="Log out"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center space-x-2">
              <Link
                to="/login"
                className="px-3.5 py-1.5 text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition"
              >
                Sign in
              </Link>
              <Link
                to="/register"
                className="rounded-xl bg-emerald-600 hover:bg-emerald-700 px-3.5 py-1.5 text-sm font-semibold text-white shadow-sm transition"
              >
                Get Started
              </Link>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};
