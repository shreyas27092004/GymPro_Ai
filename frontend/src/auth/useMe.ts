// src/auth/useMe.ts
import { useAuth } from './AuthContext';

export const useMe = () => {
  const { me, isLoading, token, refreshMe } = useAuth();
  return { me, isLoading, token, refreshMe };
};
