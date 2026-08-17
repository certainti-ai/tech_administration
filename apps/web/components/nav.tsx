"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/assets", label: "Assets" },
  { href: "/licenses", label: "Licences" },
  { href: "/people", label: "People" },
  { href: "/access-requests", label: "Access requests" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function MainNav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-line pt-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          Certainti <span className="text-ink-2">Tech Administration</span>
        </Link>
      </div>
      <nav aria-label="Primary" className="-mb-px mt-4 flex gap-1 overflow-x-auto">
        {LINKS.map((link) => {
          const active = isActive(pathname, link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-current={active ? "page" : undefined}
              className={[
                "whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
                active
                  ? "border-series-1 font-medium text-ink"
                  : "border-transparent text-ink-2 hover:text-ink",
              ].join(" ")}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
