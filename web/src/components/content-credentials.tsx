"use client";

import Image from "next/image";
import { useEffect, useState } from "react";

// Reads and displays standard C2PA Content Credentials embedded in an image, using
// @contentauth/c2pa-web (the maintained CAI data SDK; the c2pa-wc display component is deprecated,
// so the UI is hand-built per the C2PA 2.0 UX recommendations). The SDK is loaded with a dynamic
// import() inside the effect so its worker/WASM only run in the browser, never during SSR. The image
// is signed with a C2PA test certificate; validating against the C2PA conformance test trust list
// reaches the green "Trusted" state, labeled FOR TESTING ONLY (production uses the C2PA production
// trust list). The honest test-only framing is shown next to the badge.

type Credentials = {
  title?: string;
  claimGenerator?: string;
  format?: string;
  issuer?: string;
  time?: string;
  assertions: string[];
  validationState?: string;
};

const SRC = "/credentialed-sample.jpg";

export function ContentCredentials() {
  const [cc, setCc] = useState<Credentials | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { createC2pa } = await import("@contentauth/c2pa-web/inline");
        const c2pa = await createC2pa();
        const blob = await (await fetch(SRC)).blob();
        // Validate against the C2PA conformance test trust list (the test root anchors + the allowed
        // signing EKUs) so the signing certificate's issuer is checked, not just the signature: with
        // the matching test anchors the manifest validates as the green "Trusted" state, not just
        // "Valid". If the trust files can't be fetched, fall back to a plain read (reports "Valid").
        const reader = await (async () => {
          try {
            const [anchors, cfg] = await Promise.all([
              fetch("/c2pa-trust/anchors.pem").then((r) => (r.ok ? r.text() : Promise.reject(r))),
              fetch("/c2pa-trust/store.cfg").then((r) => (r.ok ? r.text() : Promise.reject(r))),
            ]);
            return c2pa.reader.fromBlob("image/jpeg", blob, {
              verify: { verifyTrust: true },
              trust: { trustAnchors: anchors, trustConfig: cfg },
            });
          } catch {
            return c2pa.reader.fromBlob("image/jpeg", blob);
          }
        })();
        if (!reader) {
          if (!cancelled) {
            setError("No Content Credentials found in this asset.");
            setLoading(false);
          }
          return;
        }
        try {
          const store = await reader.json();
          const active = store?.manifests?.[store?.active_manifest] ?? {};
          const sig = active?.signature_info ?? {};
          if (!cancelled) {
            setCc({
              title: active?.title,
              claimGenerator: active?.claim_generator,
              format: active?.format,
              issuer: sig?.issuer,
              time: sig?.time,
              assertions: (active?.assertions ?? [])
                .map((a: { label?: string }) => a?.label)
                .filter(Boolean),
              validationState: store?.validation_state,
            });
            setLoading(false);
          }
        } finally {
          await reader.free(); // WASM heap is not GC'd; always free.
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to read Content Credentials.");
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="rounded-xl border border-white/15 bg-white/[0.03] p-5 backdrop-blur-md">
      <h2 className="mb-1 text-xs uppercase tracking-widest text-white/50">
        C2PA Content Credentials
      </h2>
      <p className="mb-3 text-[11px] text-white/55">
        Read in the browser from a separately C2PA-credentialed sample, and validated against the
        C2PA conformance test trust list to show the green Trusted state. The recovered asset is
        stripped, so its provenance comes from the repository.
      </p>

      {loading && <p className="font-mono text-sm text-white/50">Reading credentials…</p>}
      {error && <p className="font-mono text-sm text-amber-400">{error}</p>}

      {cc && (
        <div className="grid gap-4 sm:grid-cols-[8rem_1fr]">
          <Image
            src={SRC}
            alt="C2PA-credentialed asset"
            width={128}
            height={128}
            className="h-32 w-32 rounded-lg border border-white/10 object-cover"
          />
          <div>
            <div className="mb-2 flex items-center gap-2">
              <span
                className="inline-flex h-6 w-6 items-center justify-center rounded-full rounded-br-none border border-emerald-300/70 font-mono text-[10px] font-semibold lowercase text-emerald-300"
                title="Content Credentials"
              >
                cr
              </span>
              <span
                className={`font-mono text-xs ${
                  cc.validationState === "Trusted" ? "text-emerald-300" : "text-amber-300"
                }`}
              >
                {cc.validationState ?? "Valid"}
              </span>
            </div>
            <dl className="grid gap-1 font-mono text-xs text-white/70">
              <Row k="produced by" v={cc.claimGenerator} />
              <Row k="format" v={cc.format} />
              <Row k="signed by" v={cc.issuer} />
              <Row k="signed at" v={cc.time} />
              <Row k="assertions" v={cc.assertions.join(", ")} />
            </dl>
            <p className="mt-2 text-[11px] text-white/55">
              {cc.validationState === "Trusted"
                ? "Trusted against the C2PA conformance test trust list. The test certificate is marked FOR TESTING ONLY; a production deployment validates against the C2PA production trust list."
                : "Signed with a C2PA test certificate: the signature is valid, not the green Trusted state (which needs a Conformance-Program CA)."}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}

function Row({ k, v }: { k: string; v?: string }) {
  if (!v) return null;
  return (
    <div className="flex gap-3">
      <dt className="w-24 shrink-0 text-white/55">{k}</dt>
      <dd className="break-all text-white/80">{v}</dd>
    </div>
  );
}
