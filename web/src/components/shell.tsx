"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Home, Settings } from "lucide-react";
import { DbWordmark } from "@/brand";
import { Button, Link as TextLink, Typography } from "@/ui";

const links = [
  { href: "/", label: "Home", icon: Home },
  { href: "/settings", label: "Settings", icon: Settings },
];

function current(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggleTheme() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("podcastbox-theme", next ? "dark" : "light");
    setDark(next);
  }

  return (
    <div className="app-shell" style={{ minBlockSize: "100dvh", display: "flex", flexDirection: "column" }}>
      <div className="page-haze" aria-hidden="true" />
      <header className="inbox-brief-header">
        <div className="brand-bar">
          <Link href="/" className="brand-lockup">
            <DbWordmark />
            <Typography variant="subtitle-2" tag="span" className="brand-product">
              PodcastBox
            </Typography>
          </Link>
          <Button colorScheme="tertiary" className="touch-44" aria-pressed={dark} onClick={toggleTheme}>
            {dark ? "Light theme" : "Dark theme"}
          </Button>
        </div>
      </header>
      <main className="inbox-brief-main">{children}</main>
      <nav className="pb-bottom-nav" aria-label="Sections">
        <div className="pb-bottom-nav-track">
          {links.map((link) => {
            const on = current(pathname, link.href);
            const Icon = link.icon;
            return (
              <TextLink
                key={link.href}
                noUnderline
                className="pb-nav-pill"
                aria-current={on ? "page" : undefined}
                element={<Link href={link.href} />}
              >
                <Icon aria-hidden="true" />
                <span className="pb-nav-label">{link.label}</span>
              </TextLink>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
