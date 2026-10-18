import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { RequireRole } from './auth/RequireRole';
import { Navbar } from './components/Navbar';
import { GymProCoach } from './coach/GymProCoach';

// Pages
import { LandingPage } from './pages/public/LandingPage';
import { RegisterPage } from './pages/public/RegisterPage';
import { VerifyPage } from './pages/public/VerifyPage';
import { LoginPage } from './pages/public/LoginPage';
import { ForgotPage } from './pages/public/ForgotPage';
import { ResetPasswordPage } from './pages/public/ResetPasswordPage';

import { OnboardingPage } from './pages/member/OnboardingPage';
import { MemberDashboard } from './pages/member/MemberDashboard';
import { MembershipPage } from './pages/member/MembershipPage';
import { PrivacyPage } from './pages/member/PrivacyPage';

import { TrainerConsole } from './pages/trainer/TrainerConsole';
import { AdminConsole } from './pages/admin/AdminConsole';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function AppContent() {
  const { me } = useAuth();
  const [coachOpen, setCoachOpen] = useState(false);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 flex flex-col font-sans transition-colors duration-200">
      <Navbar onOpenCoach={() => setCoachOpen(true)} />

      <main className="flex-1">
        <Routes>
          {/* Public Routes */}
          <Route path="/" element={<LandingPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verify" element={<VerifyPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot" element={<ForgotPage />} />
          <Route path="/reset" element={<ResetPasswordPage />} />

          {/* Member Protected Routes (USER) */}
          <Route element={<RequireRole roles={['USER']} />}>
            <Route path="/onboarding" element={<OnboardingPage />} />
            <Route path="/app" element={<MemberDashboard onOpenCoach={() => setCoachOpen(true)} />} />
            <Route path="/app/membership" element={<MembershipPage />} />
            <Route path="/app/privacy" element={<PrivacyPage />} />
          </Route>

          {/* Trainer Protected Routes (TRAINER) */}
          <Route element={<RequireRole roles={['TRAINER']} />}>
            <Route path="/trainer" element={<TrainerConsole onOpenCoach={() => setCoachOpen(true)} />} />
          </Route>

          {/* Admin Protected Routes (ADMIN) */}
          <Route element={<RequireRole roles={['ADMIN']} />}>
            <Route path="/admin" element={<AdminConsole onOpenCoach={() => setCoachOpen(true)} />} />
          </Route>

          {/* Fallback */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      {/* AI Coach Drawer (available across authenticated app) */}
      {me && (
        <GymProCoach
          isOpen={coachOpen}
          onClose={() => setCoachOpen(false)}
          conversationId={me.user_id}
        />
      )}
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <AppContent />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
