import SwiftUI

// Compact result UI for the share extension. Same palette and the same honest
// states as the app's Verify tab (it renders the shared VerifyViewModel),
// sized for the share-sheet context. A Done button always completes the
// extension request.
struct ShareResultView: View {
    @ObservedObject var viewModel: VerifyViewModel
    let onDone: () -> Void

    var body: some View {
        ZStack {
            RootedBackdrop()
            VStack(spacing: 16) {
                header
                Spacer(minLength: 12)
                stateContent
                Spacer(minLength: 12)
                doneButton
            }
            .padding(24)
        }
        .preferredColorScheme(.dark)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.seal")
                .foregroundStyle(RootedTheme.emerald)
            Text("Verify with Rooted")
                .font(.headline)
                .foregroundStyle(Color.white)
            Spacer(minLength: 0)
        }
    }

    // MARK: State content

    @ViewBuilder
    private var stateContent: some View {
        switch viewModel.state {
        case .idle:
            progress("Reading the shared image")
        case .uploading:
            progress("Matching against the live registry")
        case .matched(let manifest, let similarityScore, let proof):
            matchedContent(manifest: manifest, similarityScore: similarityScore, proof: proof)
        case .noMatch:
            noMatchContent
        case .error(let message):
            errorContent(message)
        }
    }

    private func progress(_ caption: String) -> some View {
        VStack(spacing: 14) {
            ProgressView()
                .controlSize(.large)
                .tint(RootedTheme.mint)
            Text(caption)
                .font(.subheadline)
                .foregroundStyle(RootedTheme.dim)
        }
        .padding(.vertical, 24)
    }

    private func matchedContent(manifest: Manifest, similarityScore: Double, proof: TransparencyProof) -> some View {
        VStack(spacing: 16) {
            // Emerald only when the live Merkle proof verified on the server;
            // anything else gets the honest warm state.
            if proof.serverVerified {
                Label("VERIFIED", systemImage: "checkmark.seal.fill")
                    .foregroundStyle(Color.black)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 9)
                    .background(Capsule().fill(RootedTheme.emerald))
                    .font(.subheadline.weight(.bold))
            } else {
                Label("PROOF NOT VERIFIED", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(Color.black)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 9)
                    .background(Capsule().fill(RootedTheme.warm))
                    .font(.subheadline.weight(.bold))
            }

            VStack(alignment: .leading, spacing: 12) {
                row("Manifest", manifest.manifestId.truncatedMiddle(head: 14, tail: 10), monospaced: true)
                row("Model", manifest.systemProvenance?.model ?? "not recorded")
                row("Provider", manifest.systemProvenance?.provider ?? "not recorded")
                row("Similarity", String(format: "%.0f / 100", similarityScore))
                row("Merkle proof", "leaf \(proof.leafIndex) of \(proof.treeSize)")
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16).fill(Color.white.opacity(0.05)))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(RootedTheme.emerald.opacity(0.25), lineWidth: 1))
        }
    }

    private var noMatchContent: some View {
        VStack(spacing: 12) {
            Image(systemName: "questionmark.circle")
                .font(.system(size: 36, weight: .light))
                .foregroundStyle(RootedTheme.warm)
            Text("No provenance found")
                .font(.title3.weight(.semibold))
                .foregroundStyle(Color.white)
            Text("No provenance found in the registry for this image. It either was never registered or has been altered beyond recovery.")
                .font(.footnote)
                .foregroundStyle(RootedTheme.dim)
                .multilineTextAlignment(.center)
        }
        .padding(.vertical, 16)
    }

    private func errorContent(_ message: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 36, weight: .light))
                .foregroundStyle(RootedTheme.warm)
            Text("Verification failed")
                .font(.title3.weight(.semibold))
                .foregroundStyle(Color.white)
            Text(message)
                .font(.footnote)
                .foregroundStyle(RootedTheme.dim)
                .multilineTextAlignment(.center)
        }
        .padding(.vertical, 16)
    }

    private var doneButton: some View {
        Button(action: onDone) {
            Text("Done")
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(RoundedRectangle(cornerRadius: 14).fill(RootedTheme.emerald))
                .foregroundStyle(Color.black)
        }
    }

    private func row(_ label: String, _ value: String, monospaced: Bool = false) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(RootedTheme.dim)
                .frame(width: 92, alignment: .leading)
            Text(value)
                .font(monospaced ? .system(.footnote, design: .monospaced) : .footnote)
                .foregroundStyle(Color.white)
                .multilineTextAlignment(.leading)
            Spacer(minLength: 0)
        }
    }
}
