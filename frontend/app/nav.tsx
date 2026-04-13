"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";

const links = [
  { href: "/", label: "Browse" },
  { href: "/outfits", label: "Outfits" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="flex items-center gap-8 text-sm tracking-wide">
      {links.map(({ href, label }) => {
        const active = pathname === href;
        return (
          <Link
            key={href}
            href={href}
            className={`hover:text-blush transition-colors ${
              active ? "text-charcoal" : "text-charcoal/50"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
