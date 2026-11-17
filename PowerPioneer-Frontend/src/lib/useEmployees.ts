import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Employee } from "../api/types";

let cache: Promise<Employee[]> | null = null;
const listeners = new Set<() => void>();

/** Employee directory (any authenticated user may read it). Cached app-wide. */
export function loadEmployees(force = false): Promise<Employee[]> {
  if (!cache || force) {
    cache = api.listAll<Employee>("/employees/", { ordering: "last_name" });
    cache.catch(() => {
      cache = null;
    });
    if (force) listeners.forEach((listener) => listener());
  }
  return cache;
}

/** Call after creating/updating/deleting employees so every page refreshes. */
export function invalidateEmployees() {
  void loadEmployees(true);
}

export function clearEmployeeCache() {
  cache = null;
}

export function useEmployees() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const listener = () => setVersion((v) => v + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadEmployees()
      .then((list) => {
        if (!cancelled) setEmployees(list);
      })
      .catch(() => {
        if (!cancelled) setEmployees([]);
      });
    return () => {
      cancelled = true;
    };
  }, [version]);

  const byId = useMemo(() => new Map(employees.map((e) => [e.employee_id, e])), [employees]);
  const nameOf = (id: string | null | undefined) => (id ? byId.get(id)?.full_name ?? "Unknown" : "—");

  return { employees, byId, nameOf };
}
