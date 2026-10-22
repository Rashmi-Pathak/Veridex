import SwiftUI

@main
struct RootedApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

struct ContentView: View {
    var body: some View {
        TabView {
            VerifyView()
                .tabItem { Label("Verify", systemImage: "checkmark.seal") }
            LogView()
                .tabItem { Label("Log", systemImage: "list.bullet.rectangle") }
            AboutView()
                .tabItem { Label("About", systemImage: "info.circle") }
        }
        .tint(RootedTheme.emerald)
        .preferredColorScheme(.dark)
    }
}
