import SwiftUI

// Rooted brand palette, kept in code so the project needs no asset catalog.
enum RootedTheme {
    // Near-black green background, #060A09.
    static let background = Color(red: 6.0 / 255.0, green: 10.0 / 255.0, blue: 9.0 / 255.0)
    // Emerald accent, #34D399.
    static let emerald = Color(red: 52.0 / 255.0, green: 211.0 / 255.0, blue: 153.0 / 255.0)
    // Mint highlight, #5EFBD2.
    static let mint = Color(red: 94.0 / 255.0, green: 251.0 / 255.0, blue: 210.0 / 255.0)
    // Warm accent for honest warning states, #FFB86B.
    static let warm = Color(red: 255.0 / 255.0, green: 184.0 / 255.0, blue: 107.0 / 255.0)
    // Secondary text.
    static let dim = Color.white.opacity(0.6)
}

// Shared backdrop: the near-black green with a faint emerald radial glow.
struct RootedBackdrop: View {
    var body: some View {
        ZStack {
            RootedTheme.background
            RadialGradient(
                colors: [RootedTheme.emerald.opacity(0.10), Color.clear],
                center: .top,
                startRadius: 0,
                endRadius: 460
            )
        }
        .ignoresSafeArea()
    }
}

extension String {
    // Middle truncation for long ids and hashes, keeping both ends readable.
    func truncatedMiddle(head: Int = 12, tail: Int = 8) -> String {
        guard count > head + tail + 1 else { return self }
        return "\(prefix(head))\u{2026}\(suffix(tail))"
    }
}
