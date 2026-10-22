import { AgentPanel } from "@/components/agent-panel";
import { AudioPanel } from "@/components/audio-panel";
import { B2EventsPanel } from "@/components/b2-events-panel";
import { ByoUploadPanel } from "@/components/byo-upload-panel";
import { CheckpointHistoryPanel } from "@/components/checkpoint-history-panel";
import { CheckpointLockPanel } from "@/components/checkpoint-lock-panel";
import { ComparisonPanel } from "@/components/comparison-panel";
import { ConsistencyPanel } from "@/components/consistency-panel";
import { ContentCredentials } from "@/components/content-credentials";
import { FederationPanel } from "@/components/federation-panel";
import { GenblazePanel } from "@/components/genblaze-panel";
import { GenblazeVerifyPanel } from "@/components/genblaze-verify-panel";
import { GeneratePanel } from "@/components/generate-panel";
import { Hero } from "@/components/hero";
import { IntegrityClashPanel } from "@/components/integrity-clash-panel";
import { LineagePanel } from "@/components/lineage-panel";
import { ProvidersPanel } from "@/components/providers-panel";
import { RebuildPanel } from "@/components/rebuild-panel";
import { ReceiptPanel } from "@/components/receipt-panel";
import { RecoverPanel } from "@/components/recover-panel";
import { RecoverStrip } from "@/components/recover-strip";
import { RemarkPanel } from "@/components/remark-panel";
import { RobustnessPanel } from "@/components/robustness-panel";
import { SectionNav } from "@/components/section-nav";
import { StatusPanel } from "@/components/status-panel";
import { StoragePanel } from "@/components/storage-panel";
import { SupportedAlgorithms } from "@/components/supported-algorithms";
import { TamperPanel } from "@/components/tamper-panel";
import { TranscriptPanel } from "@/components/transcript-panel";
import { VideoPanel } from "@/components/video-panel";
import { WhenVisible } from "@/components/when-visible";
import { MerkleExplorer } from "@/components/three/merkle-explorer";

// The page reads as a narrative: the lead (hero + the headline recover strip) sits above a sticky
// scroll-spy nav, then the panels are grouped into ordered acts. Each act is a <section> with a
// stable id (the nav anchors to it), an eyebrow + title + one-line subtitle, scroll-mt so the sticky
// nav never covers the heading on jump, and the existing gap-8 stack of panels. The act wrappers and
// the nav are the only additions; no panel's behavior or copy changes.
type Act = {
  id: string;
  eyebrow: string;
  title: string;
  subtitle: string;
};

function ActHeader({ eyebrow, title, subtitle }: Omit<Act, "id">) {
  return (
    <header className="space-y-1.5">
      <p className="font-mono text-[11px] uppercase tracking-widest text-white/45">{eyebrow}</p>
      <h2 className="text-2xl font-semibold tracking-tight text-white/90">{title}</h2>
      <p className="max-w-xl text-sm text-white/55">{subtitle}</p>
    </header>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-6 py-16">
      <Hero />

      <RecoverStrip />

      <SectionNav />

      <section id="loop" className="flex scroll-mt-24 flex-col gap-8">
        <ActHeader
          eyebrow="Act 01 · Core"
          title="The recovery loop"
          subtitle="Generate a signed asset, strip it, then recover the manifest from an invisible watermark or a perceptual hash."
        />
        <WhenVisible>
          <GeneratePanel />
        </WhenVisible>
        <WhenVisible>
          <RecoverPanel />
        </WhenVisible>
        <WhenVisible>
          <ComparisonPanel />
        </WhenVisible>
        <WhenVisible>
          <RobustnessPanel />
        </WhenVisible>
        <WhenVisible>
          <ProvidersPanel />
        </WhenVisible>
      </section>

      <section id="modalities" className="flex scroll-mt-24 flex-col gap-8">
        <ActHeader
          eyebrow="Act 02 · Reach"
          title="Every modality"
          subtitle="The same recovery loop closes for audio, video, and speech-to-text transcripts."
        />
        <WhenVisible>
          <AudioPanel />
        </WhenVisible>
        <WhenVisible>
          <VideoPanel />
        </WhenVisible>
        <WhenVisible>
          <TranscriptPanel />
        </WhenVisible>
      </section>

      <section id="trust" className="flex scroll-mt-24 flex-col gap-8">
        <ActHeader
          eyebrow="Act 03 · Standards"
          title="Standards-grade trust"
          subtitle="C2PA Content Credentials, tamper forensics, ingredient lineage, and the algorithms on offer."
        />
        <WhenVisible>
          <ContentCredentials />
        </WhenVisible>
        <WhenVisible>
          <TamperPanel />
        </WhenVisible>
        <WhenVisible>
          <IntegrityClashPanel />
        </WhenVisible>
        <WhenVisible>
          <RemarkPanel />
        </WhenVisible>
        <WhenVisible>
          <LineagePanel />
        </WhenVisible>
        <WhenVisible>
          <ReceiptPanel />
        </WhenVisible>
        <WhenVisible>
          <SupportedAlgorithms />
        </WhenVisible>
      </section>

      <section id="backblaze" className="flex scroll-mt-24 flex-col gap-8">
        <ActHeader
          eyebrow="Act 04 · Storage"
          title="Backblaze B2"
          subtitle="Where every asset, manifest, and signed checkpoint lives, with event-driven ingest straight from the bucket."
        />
        <WhenVisible>
          <StoragePanel />
        </WhenVisible>
        <WhenVisible>
          <B2EventsPanel />
        </WhenVisible>
        <WhenVisible>
          <ByoUploadPanel />
        </WhenVisible>
        <WhenVisible>
          <RebuildPanel />
        </WhenVisible>
        <WhenVisible>
          <GenblazePanel />
        </WhenVisible>
        <WhenVisible>
          <GenblazeVerifyPanel />
        </WhenVisible>
      </section>

      <section id="log" className="flex scroll-mt-24 flex-col gap-8">
        <ActHeader
          eyebrow="Act 05 · Proof"
          title="The transparency log"
          subtitle="A Merkle log with WORM-sealed, signed checkpoints that anyone can re-verify."
        />
        <WhenVisible minHeight={320}>
          <MerkleExplorer />
        </WhenVisible>
        <WhenVisible>
          <CheckpointLockPanel />
        </WhenVisible>
        <WhenVisible>
          <ConsistencyPanel />
        </WhenVisible>
        <WhenVisible>
          <CheckpointHistoryPanel />
        </WhenVisible>
      </section>

      <section id="network" className="flex scroll-mt-24 flex-col gap-8">
        <ActHeader
          eyebrow="Act 06 · Open"
          title="Open network and agents"
          subtitle="Federated resolvers, live service status, and an MCP agent that verifies provenance on request."
        />
        <WhenVisible>
          <FederationPanel />
        </WhenVisible>
        <WhenVisible>
          <StatusPanel />
        </WhenVisible>
        <WhenVisible>
          <AgentPanel />
        </WhenVisible>
      </section>

      <p className="font-mono text-xs text-white/50">
        Next 15, React 19, Tailwind v4, R3F, typed against the FastAPI SBR API.
      </p>
    </main>
  );
}
