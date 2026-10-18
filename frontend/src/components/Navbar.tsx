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
    <nav className="sticky top-0 z-40 border-b border-border bg-surface/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8 h-16">
        {/* Brand */}
        <div className="flex items-center space-x-6">
          <Link to="/" className="flex items-center space-x-2.5 min-h-[44px]">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent/10 text-accent">
              <Dumbbell className="h-5 w-5" />
            </div>
            <span className="text-lg font-extrabold tracking-tight text-text-primary">
              GymPro <span className="text-accent">AI</span>
            </span>
          </Link>

          {/* Navigation Links for Authenticated Users */}
          {me && (
            <div className="hidden md:flex items-center space-x-1 text-sm font-medium">
              {me.role === 'USER' && (
                <>
                  <Link
                    to="/app"
                    className={`flex items-center gap-1.5 px-3 py-2 min-h-[44px] rounded-lg transition ${
                      isActive('/app')
                        ? 'bg-surface-raised text-accent font-semibold'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    <Calendar className="h-4 w-4" /> Dashboard
                  </Link>
                  <Link
                    to="/app/membership"
                    className={`flex items-center gap-1.5 px-3 py-2 min-h-[44px] rounded-lg transition ${
                      isActive('/app/membership')
                        ? 'bg-surface-raised text-accent font-semibold'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    <CreditCard className="h-4 w-4" /> Membership
                  </Link>
                  <Link
                    to="/app/privacy"
                    className={`flex items-center gap-1.5 px-3 py-2 min-h-[44px] rounded-lg transition ${
                      isActive('/app/privacy')
                        ? 'bg-surface-raised text-accent font-semibold'
                        : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    <Lock className="h-4 w-4" /> Privacy
                  </Link>
                </>
              )}

              {me.role === 'TRAINER' && (
                <Link
                  to="/trainer"
                  className={`flex items-center gap-1.5 px-3 py-2 min-h-[44px] rounded-lg transition ${
                    isActive('/trainer')
                      ? 'bg-surface-raised text-accent font-semibold'
                      : 'text-text-muted hover:text-text-primary'
                  }`}
                >
                  <UserCheck className="h-4 w-4" /> Trainer Console
                </Link>
              )}

              {me.role === 'ADMIN' && (
                <Link
                  to="/admin"
                  className={`flex items-center gap-1.5 px-3 py-2 min-h-[44px] rounded-lg transition ${
                    isActive('/admin')
                      ? 'bg-surface-raised text-accent font-semibold'
                      : 'text-text-muted hover:text-text-primary'
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
            className="flex items-center justify-center min-h-[44px] min-w-[44px] rounded-lg text-text-muted hover:bg-surface-raised transition"
          >
            {theme === 'dark' ? <Sun className="h-5 w-5 text-amber-400" /> : <Moon className="h-5 w-5" />}
          </button>

          {/* AI Coach Trigger Button */}
          {me && (
            <button
              onClick={onOpenCoach}
              className="flex items-center gap-1.5 rounded-xl bg-accent hover:bg-accent-hover px-4 min-h-[44px] text-xs font-semibold text-white shadow-sm transition"
              aria-label="Open AI Assistant"
            >
              <Sparkles className="h-4 w-4" />
              <span className="hidden sm:inline">AI Coach</span>
            </button>
          )}

          {/* User Profile / Logout or Public Sign In */}
          {me ? (
            <div className="flex items-center space-x-2 pl-2 border-l border-border">
              <div className="hidden sm:block text-right">
                <p className="text-xs font-semibold text-text-primary">{me.full_name}</p>
                <div className="flex items-center justify-end gap-1">
                  <span className="inline-block rounded bg-surface-raised px-1.5 py-0.5 text-[10px] font-mono text-text-muted">
                    {me.role}
                  </span>
                  {me.cooling_off_active && (
                    <span className="rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 px-1 py-0.5 text-[9px] font-semibold">
                      Cooling Off
                    </span>
                  )}
                </div>
              </div>

              <button
                onClick={handleLogout}
                aria-label="Log out"
                className="flex items-center justify-center min-h-[44px] min-w-[44px] rounded-lg text-text-muted hover:text-danger hover:bg-danger/10 transition"
                title="Log out"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center space-x-2">
              <Link
                to="/login"
                className="flex items-center justify-center px-3.5 min-h-[44px] text-sm font-medium text-text-muted hover:text-text-primary transition"
              >
                Sign in
              </Link>
              <Link
                to="/register"
                className="flex items-center justify-center rounded-xl bg-accent hover:bg-accent-hover px-4 min-h-[44px] text-sm font-semibold text-white shadow-sm transition"
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
