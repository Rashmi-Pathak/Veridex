import XCTest
@testable import Rooted

final class MultipartBodyTests: XCTestCase {
    private let boundary = "rooted-boundary-test"
    // Deliberately not valid UTF-8 so the byte-equality check proves the
    // payload travels unmodified.
    private let payload = Data([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x01, 0x02, 0x03])

    private var body: Data {
        MultipartForm.body(
            boundary: boundary,
            fieldName: "file",
            filename: "capture.jpg",
            contentType: "image/jpeg",
            fileData: payload
        )
    }

    func testBodyHasBoundaryAndHeaders() {
        let text = String(decoding: body, as: UTF8.self)
        XCTAssertTrue(text.hasPrefix("--\(boundary)\r\n"))
        XCTAssertTrue(text.contains("Content-Disposition: form-data; name=\"file\"; filename=\"capture.jpg\"\r\n"))
        XCTAssertTrue(text.contains("Content-Type: image/jpeg\r\n\r\n"))
        XCTAssertTrue(text.hasSuffix("\r\n--\(boundary)--\r\n"))
    }

    func testBodyBytesAreExact() {
        let header = Data(
            "--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"capture.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".utf8
        )
        let closing = Data("\r\n--\(boundary)--\r\n".utf8)
        XCTAssertEqual(body, header + payload + closing)
    }

    func testPayloadBytesArePresentUnmodified() {
        XCTAssertNotNil(body.range(of: payload))
    }
}
