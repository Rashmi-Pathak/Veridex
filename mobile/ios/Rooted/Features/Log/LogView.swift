import SwiftUI

struct LogView: View {
    @StateObject private var viewModel = LogViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                RootedBackdrop()
                content
            }
            .navigationTitle("Transparency Log")
            .toolbarBackground(.hidden, for: .navigationBar)
        }
        .preferredColorScheme(.dark)
        .task { await viewModel.loadIfNeeded() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .loading:
            VStack(spacing: 12) {
                ProgressView()
                    .tint(RootedTheme.mint)
                Text("Reading the live transparency log")
                    .font(.footnote)
                    .foregroundStyle(RootedTheme.dim)
            }
        case .error(let message):
            VStack(spacing: 14) {
                Image(systemName: "antenna.radiowaves.left.and.right.slash")
                    .font(.system(size: 36, weight: .light))
                    .foregroundStyle(RootedTheme.warm)
                Text("Could not reach the transparency log")
                    .font(.headline)
                    .foregroundStyle(Color.white)
                Text(message)
                    .font(.footnote)
                    .foregroundStyle(RootedTheme.dim)
                    .multilineTextAlignment(.center)
                Button("Retry") {
                    Task { await viewModel.loadIfNeeded() }
                }
                .buttonStyle(.bordered)
                .tint(RootedTheme.emerald)
            }
            .padding(32)
        case .loaded(let log):
            logList(log)
        }
    }

    private func logList(_ log: TransparencyLog) -> some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Tree size")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(RootedTheme.dim)
                        Spacer()
                        Text("\(log.treeSize) entries")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(RootedTheme.mint)
                    }
                    Text("Root \(log.rootHash)")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(RootedTheme.dim)
                        .lineLimit(2)
                }
                .listRowBackground(Color.white.opacity(0.05))
            }
            Section {
                ForEach(log.entries) { entry in
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text("#\(entry.leafIndex)")
                            .font(.system(.footnote, design: .monospaced))
                            .foregroundStyle(RootedTheme.emerald)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(entry.manifestId.truncatedMiddle(head: 18, tail: 8))
                                .font(.system(.footnote, design: .monospaced))
                                .foregroundStyle(Color.white)
                            Text("\(entry.leafHash.prefix(16))\u{2026}")
                                .font(.system(.caption2, design: .monospaced))
                                .foregroundStyle(RootedTheme.dim)
                        }
                    }
                    .listRowBackground(Color.white.opacity(0.03))
                }
            } header: {
                Text("Signed entries, oldest first")
                    .foregroundStyle(RootedTheme.dim)
            }
        }
        .scrollContentBackground(.hidden)
        .refreshable { await viewModel.load() }
    }
}
