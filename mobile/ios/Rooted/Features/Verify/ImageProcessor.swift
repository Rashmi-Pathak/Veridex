import UIKit

// Downscales a picked or captured image before upload. The matcher works on
// perceptual features, so 1600px on the longest side keeps uploads small
// without hurting recovery. Images already at or under the limit pass through
// at their original pixel size.
enum ImageProcessor {
    static let defaultMaxDimension: CGFloat = 1600
    static let defaultJPEGQuality: CGFloat = 0.85

    static func downscaledJPEGData(
        from image: UIImage,
        maxDimension: CGFloat = ImageProcessor.defaultMaxDimension,
        quality: CGFloat = ImageProcessor.defaultJPEGQuality
    ) -> Data? {
        let pixelWidth = image.size.width * image.scale
        let pixelHeight = image.size.height * image.scale
        let longestSide = max(pixelWidth, pixelHeight)
        guard longestSide > 0 else { return nil }

        let scale = min(1.0, maxDimension / longestSide)
        let targetSize = CGSize(
            width: max(1.0, (pixelWidth * scale).rounded()),
            height: max(1.0, (pixelHeight * scale).rounded())
        )

        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: targetSize, format: format)
        let scaled = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: targetSize))
        }
        return scaled.jpegData(compressionQuality: quality)
    }
}
