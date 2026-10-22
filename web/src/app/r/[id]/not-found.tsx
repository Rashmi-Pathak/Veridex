import type { Metadata } from "next";
import Link from "next/link";

// The page's generateMetadata sets robots: noindex for a missing id, but the notFound() render path
// resets the page-level title/description to the layout default, so set the on-brand 404 title here
// on the boundary itself.
export const metadata: Metadata = {
  title: "Provenance receipt not found: Veridex",
  description:
    "No provenance record found in this Veridex registry. A single instance only serves records it has ingested.",
  robots: { index: false, follow: true },
};

// Rendered with a real HTTP 404 when a receipt id is not in this Veridex registry (the page calls
// notFound()). On-brand and honest: a single instance only serves records it has ingested.
export default function ReceiptNotFound() {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-6 py-16">
      <header className="space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-white/55">
          Veridex &middot; provenance receipt
        </p>
        <h1 className="text-xl font-semibold sm:text-2xl">No provenance found</h1>
      </header>

      <div className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
        <p className="font-mono text-sm text-amber-400">
          This Veridex registry has no record for that id.
        </p>
        <p className="mt-2 text-[11px] text-white/50">
          A single instance only serves records it has ingested. The id may belong to another resolver,
          or it may never have been registered here.
        </p>
        <div className="mt-4">
          <Link href="/" className="text-xs text-blue-400 hover:underline">
            Veridex &rarr;
          </Link>
        </div>
      </div>

      <p className="text-[11px] text-white/45">Provenance proves origin, not truth.</p>
    </main>
  );
}
