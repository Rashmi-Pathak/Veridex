import XCTest
import UniformTypeIdentifiers
@testable import Rooted

final class SharePayloadTests: XCTestCase {
    private func extensionItem(_ providers: [NSItemProvider]) -> NSExtensionItem {
        let item = NSExtensionItem()
        item.attachments = providers
        return item
    }

    // A provider that can deliver JPEG bytes, registered the way the share
    // sheet registers a shared photo. public.jpeg conforms to public.image,
    // so this also proves the check is conformance-based, not exact-match.
    private func imageProvider() -> NSItemProvider {
        let provider = NSItemProvider()
        provider.registerDataRepresentation(
            forTypeIdentifier: UTType.jpeg.identifier,
            visibility: .all
        ) { completion in
            completion(Data([0xFF, 0xD8]), nil)
            return nil
        }
        return provider
    }

    private func textProvider() -> NSItemProvider {
        NSItemProvider(object: "not an image" as NSString)
    }

    func testFindsTheImageProvider() {
        let provider = imageProvider()
        let found = SharePayload.firstImageProvider(in: [extensionItem([provider])])
        XCTAssertTrue(found === provider)
    }

    func testSkipsNonImageAttachmentsAcrossItems() {
        let provider = imageProvider()
        let items = [
            extensionItem([textProvider()]),
            extensionItem([textProvider(), provider]),
        ]
        XCTAssertTrue(SharePayload.firstImageProvider(in: items) === provider)
    }

    func testReturnsNilWhenNothingIsAnImage() {
        let items = [extensionItem([textProvider()])]
        XCTAssertNil(SharePayload.firstImageProvider(in: items))
    }

    func testReturnsNilForEmptyInput() {
        XCTAssertNil(SharePayload.firstImageProvider(in: []))
        XCTAssertNil(SharePayload.firstImageProvider(in: [extensionItem([])]))
    }
}
