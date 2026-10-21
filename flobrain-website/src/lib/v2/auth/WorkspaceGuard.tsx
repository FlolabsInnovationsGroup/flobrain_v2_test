"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ErrorState, Loading, NoAccess } from "@/components/v2/states";
import { dirFor, getLocale, t } from "@/i18n";
import { clearV2Tokens, v2Client, type V2Me } from "@/lib/v2/client";

const COMPANY_TYPES = new Set(["company_member", "company_lead", "company_adm"]);

export function WorkspaceGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const locale = getLocale();
  const [me, setMe] = useState<V2Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    v2Client()
      .me()
      .then((data) => {
        if (cancelled) return;
        if (data.must_change_password) {
          router.replace("/w/first-login");
          return;
        }
        if (!data.is_platform_admin && !COMPANY_TYPES.has(data.user_type)) {
          setError("personal");
          setLoading(false);
          return;
        }
        setMe(data);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        clearV2Tokens();
        router.replace(`/w/signin?next=${encodeURIComponent(pathname || "/w")}`);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (loading) return <Loading label={t(locale, "workspace.loading")} />;
  if (error === "personal") {
    return <NoAccess label={t(locale, "workspace.personalBlocked")} />;
  }
  if (!me) {
    return (
      <ErrorState
        message={t(locale, "workspace.noAccess")}
        retryLabel={t(locale, "workspace.retry")}
      />
    );
  }
  return (
    <div className="v2-root" dir={dirFor(locale)} data-user={me.email}>
      {children}
    </div>
  );
}
