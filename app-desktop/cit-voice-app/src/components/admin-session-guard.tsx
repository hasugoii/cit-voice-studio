import { useEffect } from "react";

/** The desktop server returns 404 here; only self-host has admin sessions. */
export function AdminSessionGuard() {
  useEffect(() => {
    if (!window.location.protocol.startsWith("http")) return;
    const controller = new AbortController();
    let supported = true;
    const check = async () => {
      if (!supported || document.visibilityState === "hidden") return;
      try {
        const response = await fetch("/saas/api/admin-auth/me", {
          credentials: "same-origin", cache: "no-store", signal: controller.signal,
        });
        if (response.status === 404) supported = false;
        if (response.status === 401) {
          window.location.assign(`/saas/admin/login?next=${encodeURIComponent(window.location.pathname)}`);
        }
      } catch { /* Connectivity errors are not proof that a session expired. */ }
    };
    void check();
    const timer = window.setInterval(() => { void check(); }, 60_000);
    document.addEventListener("visibilitychange", check);
    return () => {
      controller.abort(); window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, []);
  return null;
}
