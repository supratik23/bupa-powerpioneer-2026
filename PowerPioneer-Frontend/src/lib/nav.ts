import { useCallback, useEffect, useState } from "react";

/** Pages of the app. "employee" and "manager" are the original two views. */
export const PAGES = [
  "employee",
  "manager",
  "profile",
  "wellbeing",
  "roster",
  "team-roster",
  "leave",
  "interventions",
  "chat",
  "admin",
] as const;
export type PageId = (typeof PAGES)[number];

function fromHash(): PageId {
  const id = window.location.hash.replace(/^#\/?/, "") as PageId;
  return PAGES.includes(id) ? id : "employee";
}

/** Minimal hash router so pages survive a refresh and the back button works. */
export function usePage() {
  const [page, setPage] = useState<PageId>(fromHash);

  useEffect(() => {
    const onChange = () => setPage(fromHash());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((next: PageId) => {
    if (`#/${next}` !== window.location.hash) window.location.hash = `/${next}`;
    setPage(next);
    window.scrollTo({ top: 0 });
  }, []);

  return { page, navigate };
}
