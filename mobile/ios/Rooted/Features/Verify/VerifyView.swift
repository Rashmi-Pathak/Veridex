import SwiftUI
import PhotosUI
import UIKit

struct VerifyView: View {
    @StateObject private var viewModel = VerifyViewModel()
    @State private var selectedItem: PhotosPickerItem?
    @State private var showCamera = false

    var body: some View {
        NavigationStack {
            ZStack {
                RootedBackdrop()
                ScrollView {
                    VStack(spacing: 24) {
                        stateContent
                    }
                    .padding(24)
                    .frame(maxWidth: .infinity)
                }
            }
            .navigationTitle("Verify")
            .toolbarBackground(.hidden, for: .navigationBar)
            .safeAreaInset(edge: .bottom) { pickerBar }
        }
        .preferredColorScheme(.dark)
        .onChange(of: selectedItem) { _, newItem in
            guard let item = newItem else { return }
            selectedItem = nil
            Task { await verifyPickedItem(item) }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker(
                onImage: { image in
                    showCamera = false
                    Task { await viewModel.verify(image: image) }
                },
                onCancel: { showCamera = false }
            )
            .ignoresSafeArea()
        }
    }

    // MARK: State content

    @ViewBuilder
    private var stateContent: some View {
        switch viewModel.state {
        case .idle:
            idleCard
        case .uploading:
            uploadingCard
        case .matched(let manifest, let similarityScore, let proof):
            MatchedResultView(
                manifest: manifest,
                similarityScore: similarityScore,
                proof: proof,
                onReset: { viewModel.reset() }
            )
        case .noMatch:
            noMatchCard
        case .error(let message):
            errorCard(message)
        }
    }

    private var idleCard: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.seal")
                .font(.system(size: 44, weight: .light))
                .foregroundStyle(RootedTheme.emerald)
            Text("Verify an image")
                .font(.title2.weight(.semibold))
                .foregroundStyle(Color.white)
            Text("Pick a photo or point the camera at an image. Rooted checks it against the live provenance registry and recovers the signed manifest if the image is known.")
                .font(.subheadline)
                .foregroundStyle(RootedTheme.dim)
                .multilineTextAlignment(.center)
        }
        .padding(.vertical, 48)
        .frame(maxWidth: .infinity)
    }

    private var uploadingCard: some View {
        VStack(spacing: 16) {
            ProgressView()
                .controlSize(.large)
                .tint(RootedTheme.mint)
            Text("Matching against the live registry")
                .font(.subheadline)
                .foregroundStyle(RootedTheme.dim)
        }
        .padding(.vertical, 72)
    }

    private var noMatchCard: some View {
        VStack(spacing: 14) {
            Image(systemName: "questionmark.circle")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(RootedTheme.warm)
            Text("No provenance found")
                .font(.title3.weight(.semibold))
                .foregroundStyle(Color.white)
            Text("No provenance found in the registry for this image.")
                .font(.subheadline)
                .foregroundStyle(RootedTheme.dim)
                .multilineTextAlignment(.center)
            Text("The image either was never registered or has been altered beyond recovery.")
                .font(.footnote)
                .foregroundStyle(RootedTheme.dim)
                .multilineTextAlignment(.center)
            Button("Verify another") { viewModel.reset() }
                .buttonStyle(.bordered)
                .tint(RootedTheme.emerald)
        }
        .padding(.vertical, 40)
    }

    private func errorCard(_ message: String) -> some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(RootedTheme.warm)
            Text("Verification failed")
                .font(.title3.weight(.semibold))
                .foregroundStyle(Color.white)
            Text(message)
                .font(.footnote)
                .foregroundStyle(RootedTheme.dim)
                .multilineTextAlignment(.center)
            Button("Try again") { viewModel.reset() }
                .buttonStyle(.bordered)
                .tint(RootedTheme.emerald)
        }
        .padding(.vertical, 40)
    }

    // MARK: Pickers

    private var pickerBar: some View {
        HStack(spacing: 12) {
            PhotosPicker(selection: $selectedItem, matching: .images) {
                Label("Choose Photo", systemImage: "photo.on.rectangle")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(RootedTheme.emerald)
                    .foregroundStyle(Color.black)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
            }

            Button {
                showCamera = true
            } label: {
                Label("Camera", systemImage: "camera")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(Color.white.opacity(0.08))
                    .foregroundStyle(RootedTheme.mint)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
            }
            .disabled(!CameraPicker.isCameraAvailable)
            .opacity(CameraPicker.isCameraAvailable ? 1 : 0.4)
        }
        .font(.subheadline.weight(.semibold))
        .disabled(viewModel.isBusy)
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(RootedTheme.background.opacity(0.94))
    }

    private func verifyPickedItem(_ item: PhotosPickerItem) async {
        guard let data = try? await item.loadTransferable(type: Data.self),
              let image = UIImage(data: data) else {
            viewModel.fail("Could not read the selected photo.")
            return
        }
        await viewModel.verify(image: image)
    }
}

// MARK: - Matched result

struct MatchedResultView: View {
    let manifest: Manifest
    let similarityScore: Double
    let proof: TransparencyProof
    let onReset: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            badge
            detailCard
            receiptLink
            Button("Verify another") { onReset() }
                .buttonStyle(.bordered)
                .tint(RootedTheme.mint)
        }
        .padding(.top, 16)
    }

    // The emerald VERIFIED badge is only shown when the live proof came back
    // with serverVerified true; anything else gets the honest warm state.
    private var badge: some View {
        Group {
            if proof.serverVerified {
                Label("VERIFIED", systemImage: "checkmark.seal.fill")
                    .foregroundStyle(Color.black)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 9)
                    .background(Capsule().fill(RootedTheme.emerald))
            } else {
                Label("PROOF NOT VERIFIED", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(Color.black)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 9)
                    .background(Capsule().fill(RootedTheme.warm))
            }
        }
        .font(.subheadline.weight(.bold))
    }

    private var detailCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            row("Manifest", manifest.manifestId.truncatedMiddle(head: 14, tail: 10), monospaced: true)
            divider
            row("Model", manifest.systemProvenance?.model ?? "not recorded")
            row("Provider", manifest.systemProvenance?.provider ?? "not recorded")
            row("Similarity", String(format: "%.0f / 100", similarityScore))
            divider
            row("Merkle proof", "leaf \(proof.leafIndex) of \(proof.treeSize)")
            row("Root", "\(proof.rootHash.prefix(16))\u{2026}", monospaced: true)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 18).fill(Color.white.opacity(0.05)))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(RootedTheme.emerald.opacity(0.25), lineWidth: 1))
    }

    private var divider: some View {
        Rectangle()
            .fill(Color.white.opacity(0.08))
            .frame(height: 1)
    }

    private var receiptLink: some View {
        Group {
            if let url = RootedAPI.webReceiptURL(manifestId: manifest.manifestId) {
                Link(destination: url) {
                    Label("Open web receipt", systemImage: "arrow.up.right.square")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(RoundedRectangle(cornerRadius: 14).fill(RootedTheme.mint))
                }
            }
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
