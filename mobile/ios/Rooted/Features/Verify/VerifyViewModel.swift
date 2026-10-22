import SwiftUI
import UIKit

@MainActor
final class VerifyViewModel: ObservableObject {
    enum State {
        case idle
        case uploading
        case matched(manifest: Manifest, similarityScore: Double, proof: TransparencyProof)
        case noMatch
        case error(String)
    }

    @Published var state: State = .idle

    private let client = RootedClient()

    var isBusy: Bool {
        if case .uploading = state { return true }
        return false
    }

    // Downscale, upload to the live matcher, and on a hit fetch the recovered
    // manifest and its Merkle inclusion proof in parallel. Zero matches is an
    // honest terminal state, not an error.
    func verify(image: UIImage) async {
        state = .uploading
        guard let jpeg = ImageProcessor.downscaledJPEGData(from: image) else {
            state = .error("Could not encode the image as JPEG.")
            return
        }
        do {
            let response = try await client.matchByContent(imageData: jpeg, filename: "capture.jpg")
            guard let match = response.matches.first else {
                state = .noMatch
                return
            }
            async let manifest = client.manifest(id: match.manifestId)
            async let proof = client.proof(id: match.manifestId)
            state = .matched(
                manifest: try await manifest,
                similarityScore: match.similarityScore,
                proof: try await proof
            )
        } catch {
            state = .error(error.localizedDescription)
        }
    }

    func fail(_ message: String) {
        state = .error(message)
    }

    func reset() {
        state = .idle
    }
}
