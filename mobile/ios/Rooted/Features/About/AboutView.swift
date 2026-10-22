import SwiftUI

struct AboutView: View {
    private enum StatusLine {
        case loading
        case live(ServiceStatus)
        case unavailable(String)
    }

    @State private var statusLine: StatusLine = .loading

    var body: some View {
        NavigationStack {
            ZStack {
                RootedBackdrop()
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        Text("Rooted")
                            .font(.largeTitle.weight(.bold))
                            .foregroundStyle(Color.white)

                        Text("Rooted recovers the provenance of AI-generated media after the embedded Content Credentials have been stripped. It matches an image against a live registry backed by Backblaze B2 and returns the signed manifest with a Merkle transparency proof.")
                            .font(.subheadline)
                            .foregroundStyle(RootedTheme.dim)

                        if let siteURL = URL(string: RootedAPI.webBase) {
                            Link(destination: siteURL) {
                                Label("veridex-web-phi.vercel.app", systemImage: "globe")
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(RootedTheme.mint)
                            }
                        }

                        Rectangle()
                            .fill(Color.white.opacity(0.08))
                            .frame(height: 1)

                        Text("Provenance proves origin, not truth.")
                            .font(.headline)
                            .foregroundStyle(RootedTheme.emerald)

                        statusView
                    }
                    .padding(24)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .navigationTitle("About")
            .toolbarBackground(.hidden, for: .navigationBar)
        }
        .preferredColorScheme(.dark)
        .task { await loadStatus() }
    }

    @ViewBuilder
    private var statusView: some View {
        switch statusLine {
        case .loading:
            HStack(spacing: 8) {
                ProgressView()
                    .tint(RootedTheme.dim)
                Text("Checking the live service")
                    .font(.caption)
                    .foregroundStyle(RootedTheme.dim)
            }
        case .live(let status):
            VStack(alignment: .leading, spacing: 4) {
                Label("Live: \(status.service)", systemImage: "dot.radiowaves.left.and.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(RootedTheme.emerald)
                Text("\(status.transparency.treeSize) manifests in the transparency log")
                    .font(.caption)
                    .foregroundStyle(RootedTheme.dim)
            }
        case .unavailable(let message):
            Text("Live status unavailable: \(message)")
                .font(.caption)
                .foregroundStyle(RootedTheme.warm)
        }
    }

    private func loadStatus() async {
        do {
            statusLine = .live(try await RootedClient().status())
        } catch {
            statusLine = .unavailable(error.localizedDescription)
        }
    }
}
