import XCTest
import UIKit
@testable import Rooted

final class ImageProcessorTests: XCTestCase {
    private func solidImage(width: CGFloat, height: CGFloat) -> UIImage {
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: width, height: height), format: format)
        return renderer.image { context in
            UIColor.systemGreen.setFill()
            context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        }
    }

    func testLandscapeDownscalesLongestSideTo1600() throws {
        let image = solidImage(width: 3200, height: 1600)
        let data = try XCTUnwrap(ImageProcessor.downscaledJPEGData(from: image))
        let decoded = try XCTUnwrap(UIImage(data: data))
        let width = decoded.size.width * decoded.scale
        let height = decoded.size.height * decoded.scale
        XCTAssertEqual(max(width, height), 1600, accuracy: 1)
        XCTAssertEqual(min(width, height), 800, accuracy: 1)
    }

    func testPortraitDownscalesLongestSideTo1600() throws {
        let image = solidImage(width: 1200, height: 2400)
        let data = try XCTUnwrap(ImageProcessor.downscaledJPEGData(from: image))
        let decoded = try XCTUnwrap(UIImage(data: data))
        let width = decoded.size.width * decoded.scale
        let height = decoded.size.height * decoded.scale
        XCTAssertEqual(height, 1600, accuracy: 1)
        XCTAssertEqual(width, 800, accuracy: 1)
    }

    func testSmallImageIsNotUpscaled() throws {
        let image = solidImage(width: 640, height: 480)
        let data = try XCTUnwrap(ImageProcessor.downscaledJPEGData(from: image))
        let decoded = try XCTUnwrap(UIImage(data: data))
        XCTAssertEqual(decoded.size.width * decoded.scale, 640, accuracy: 1)
        XCTAssertEqual(decoded.size.height * decoded.scale, 480, accuracy: 1)
    }

    func testOutputIsJPEG() throws {
        let image = solidImage(width: 100, height: 100)
        let data = try XCTUnwrap(ImageProcessor.downscaledJPEGData(from: image))
        // JPEG start-of-image marker.
        XCTAssertEqual(data.prefix(2), Data([0xFF, 0xD8]))
    }
}
