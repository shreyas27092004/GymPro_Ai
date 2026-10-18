// src/__tests__/routes.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RequireRole } from '../auth/RequireRole';
import { RegisterPage } from '../pages/public/RegisterPage';
import { LoginPage } from '../pages/public/LoginPage';
import { ForgotPage } from '../pages/public/ForgotPage';
import * as AuthContextModule from '../auth/AuthContext';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

describe('Route Guards & Public Pages', () => {
  it('renders RegisterPage with role tabs', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByRole('heading', { level: 2, name: /Create an Account/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Member/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Trainer/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Admin/i })).toBeInTheDocument();
  });

  it('renders LoginPage with email, password, and admin code toggle', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthContextModule.AuthProvider>
          <MemoryRouter>
            <LoginPage />
          </MemoryRouter>
        </AuthContextModule.AuthProvider>
      </QueryClientProvider>
    );

    expect(screen.getByRole('heading', { level: 2, name: /Sign In to GymPro/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/name@example.com/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Enter password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Admin Code\?/i })).toBeInTheDocument();
  });

  it('renders ForgotPage', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ForgotPage />
        </MemoryRouter>
      </QueryClientProvider>
    );

    expect(screen.getByRole('heading', { level: 2, name: /Reset Password/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Send Recovery Link/i })).toBeInTheDocument();
  });

  it('RequireRole redirects to /login if unauthenticated', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <AuthContextModule.AuthProvider>
          <MemoryRouter initialEntries={['/protected']}>
            <Routes>
              <Route path="/login" element={<div>Login Page Redirect Target</div>} />
              <Route element={<RequireRole roles={['USER']} />}>
                <Route path="/protected" element={<div>Protected Content</div>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </AuthContextModule.AuthProvider>
      </QueryClientProvider>
    );

    expect(screen.getByText('Login Page Redirect Target')).toBeInTheDocument();
    expect(screen.queryByText('Protected Content')).toBeNull();
  });
});
