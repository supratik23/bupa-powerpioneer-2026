import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, refreshAccessToken, tokens } from "../api/client";
import type { Employee, LoginResponse, RegisterPayload } from "../api/types";
import { clearEmployeeCache } from "../lib/useEmployees";

interface AuthState {
  user: Employee | null;
  /** True while the stored session is being restored on first load. */
  loading: boolean;
  /** Employee has direct reports (or is staff) and may use the team pages. */
  isManager: boolean;
  isStaff: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  reloadUser: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Employee | null>(null);
  const [hasReports, setHasReports] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    const me = await api.get<Employee>("/auth/me/");
    const reports = await api.get<Employee[]>(`/employees/${me.employee_id}/team/`);
    setHasReports(reports.length > 0);
    setUser(me);
  }, []);

  // Restore the session from stored tokens on first load.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!tokens.access && !tokens.refresh) return;
        let valid = false;
        if (tokens.access) {
          try {
            await api.post("/auth/token/verify/", { token: tokens.access }, { anonymous: true });
            valid = true;
          } catch {
            valid = false;
          }
        }
        if (!valid) valid = await refreshAccessToken();
        if (!valid) {
          tokens.clear();
          return;
        }
        await loadUser();
      } catch {
        tokens.clear();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadUser]);

  // A rejected refresh token anywhere in the app signs the user out.
  useEffect(
    () =>
      tokens.onSessionExpired(() => {
        clearEmployeeCache();
        setUser(null);
        setHasReports(false);
      }),
    [],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.post<LoginResponse>("/auth/token/", { email, password }, { anonymous: true });
      tokens.set(res.access, res.refresh);
      await loadUser();
    },
    [loadUser],
  );

  const register = useCallback(
    async (payload: RegisterPayload) => {
      await api.post("/auth/register/", payload, { anonymous: true });
      await login(payload.email, payload.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    const refresh = tokens.refresh;
    try {
      if (refresh) await api.post("/auth/logout/", { refresh });
    } catch {
      /* token may already be invalid: still sign out locally */
    }
    tokens.clear();
    clearEmployeeCache();
    setUser(null);
    setHasReports(false);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      isStaff: Boolean(user?.is_staff),
      isManager: Boolean(user?.is_staff) || hasReports,
      login,
      register,
      logout,
      reloadUser: loadUser,
    }),
    [user, loading, hasReports, login, register, logout, loadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
