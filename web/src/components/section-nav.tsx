"use client";

import { useEffect, useState } from "react";

// A sticky scroll-spy for the page's narrative acts. It mirrors the <section> ids rendered in
// page.tsx and highlights whichever act is currently in view, using an IntersectionObserver tuned to
// a band near the top of the viewport. Purely presentational: if an id is missing it simply never
// lights up, and click falls back to the anchor href. Horizontally scrollable on narrow screens.
type NavItem = { id: string; label: string };

const SECTIONS: NavItem[] = [
  { id: "loop", label: "Recovery loop" },
  { id: "modalities", label: "Modalities" },
  { id: "trust", label: "Trust" },
  { id: "backblaze", label: "Backblaze B2" },
  { id: "log", label: "Transparency log" },
  { id: "network", label: "Network" },
];

export function SectionNav() {
  const [active, setActive] = useState<string>(SECTIONS[0].id);

  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(s.id)).filter(
      (el): el is HTMLElement => el !== null,
    );
    if (els.length === 0) return;

    // The band sits between 20% and 30% down the viewport, so an act becomes active as its top
    // crosses just under the sticky nav. When several qualify, take the one nearest the top.
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 },
    );

    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, []);

  const onClick = (event: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    const el = document.getElementById(id);
    if (!el) return; // let the href fall through if the section is not on the page
    event.preventDefault();
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    if (typeof history.replaceState === "function") {
      history.replaceState(null, "", `#${id}`);
    }
    setActive(id);
  };

  return (
    <nav
      aria-label="Page sections"
      className="sticky top-0 z-30 -mx-6 border-b border-white/10 bg-[#05060a]/70 px-6 py-3 backdrop-blur-md"
    >
      <ul className="flex gap-2 overflow-x-auto [scrollbar-width:none]">
        {SECTIONS.map((s) => {
          const isActive = s.id === active;
          return (
            <li key={s.id} className="shrink-0">
              <a
                href={`#${s.id}`}
                onClick={(event) => onClick(event, s.id)}
                aria-current={isActive ? "true" : undefined}
                className={`block whitespace-nowrap rounded-full border px-3 py-1 font-mono text-xs uppercase tracking-widest transition-colors ${
                  isActive
                    ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-300"
                    : "border-white/10 text-white/50 hover:text-white/80"
                }`}
              >
                {s.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
