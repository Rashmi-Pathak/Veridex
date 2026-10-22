import SwiftUI

@MainActor
final class LogViewModel: ObservableObject {
    enum State {
        case loading
        case loaded(TransparencyLog)
        case error(String)
    }

    @Published var state: State = .loading

    private let client = RootedClient()

    // Fetches the live log. On a failed refresh the last live data stays
    // visible; the error state is only shown when there is nothing to show.
    func load() async {
        do {
            state = .loaded(try await client.log())
        } catch {
            switch state {
            case .loaded:
                break
            default:
                state = .error(error.localizedDescription)
            }
        }
    }

    // Used by .task so switching tabs does not blank out data already loaded.
    func loadIfNeeded() async {
        if case .loaded = state { return }
        state = .loading
        await load()
    }
}
