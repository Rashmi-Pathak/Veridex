import Foundation
import UniformTypeIdentifiers

// Selection logic for a share-sheet payload. It lives in the app module so
// the unit tests in RootedTests cover it, and it is also compiled into the
// RootedShare extension target, which is the code that actually runs it.
enum SharePayload {
    // The first attachment across all input items that can deliver an image.
    // Conformance-based, so concrete types like public.jpeg and public.png
    // qualify. Returns nil when nothing shared is an image.
    static func firstImageProvider(in items: [NSExtensionItem]) -> NSItemProvider? {
        items
            .flatMap { $0.attachments ?? [] }
            .first { $0.hasItemConformingToTypeIdentifier(UTType.image.identifier) }
    }
}
