package io.rooted.verify.util

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import java.io.ByteArrayOutputStream
import kotlin.math.roundToInt

// Downscales a picked or captured image before upload: longest side capped at 1600 px,
// re-encoded as JPEG quality 85. Keeps uploads small while leaving the perceptual hash and
// watermark plenty of signal.
object ImageScaler {

    const val MAX_DIMENSION = 1600
    const val JPEG_QUALITY = 85

    // Largest power-of-two sample size that still decodes at or above maxDimension on the
    // longest side. Pure math so it is unit testable without the Android framework.
    fun computeInSampleSize(width: Int, height: Int, maxDimension: Int = MAX_DIMENSION): Int {
        if (width <= 0 || height <= 0) return 1
        var sampleSize = 1
        val longest = maxOf(width, height)
        while (longest / (sampleSize * 2) >= maxDimension) {
            sampleSize *= 2
        }
        return sampleSize
    }

    // Exact target dimensions after the fine scale that follows the coarse sampled decode.
    fun scaledDimensions(width: Int, height: Int, maxDimension: Int = MAX_DIMENSION): Pair<Int, Int> {
        val longest = maxOf(width, height)
        if (longest <= maxDimension) return width to height
        val scale = maxDimension.toDouble() / longest
        val w = maxOf(1, (width * scale).roundToInt())
        val h = maxOf(1, (height * scale).roundToInt())
        return w to h
    }

    // Returns re-encoded JPEG bytes, or null when the uri does not decode as an image.
    fun loadDownscaledJpeg(resolver: ContentResolver, uri: Uri): ByteArray? {
        // In bounds-only mode decodeStream returns null BY DESIGN, so the stream open and the
        // decode result must be null-checked separately (an elvis on the use{} result would
        // reject every image; caught live on the emulator).
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        val boundsStream = resolver.openInputStream(uri) ?: return null
        boundsStream.use { stream -> BitmapFactory.decodeStream(stream, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        val options = BitmapFactory.Options().apply {
            inSampleSize = computeInSampleSize(bounds.outWidth, bounds.outHeight)
        }
        val decoded = resolver.openInputStream(uri)?.use { stream ->
            BitmapFactory.decodeStream(stream, null, options)
        } ?: return null

        val (targetW, targetH) = scaledDimensions(decoded.width, decoded.height)
        val scaled = if (targetW == decoded.width && targetH == decoded.height) {
            decoded
        } else {
            Bitmap.createScaledBitmap(decoded, targetW, targetH, true)
        }

        val out = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
        if (scaled !== decoded) decoded.recycle()
        scaled.recycle()
        return out.toByteArray()
    }
}
