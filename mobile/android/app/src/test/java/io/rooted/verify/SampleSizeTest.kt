package io.rooted.verify

import io.rooted.verify.util.ImageScaler
import org.junit.Assert.assertEquals
import org.junit.Test

// The downscale pipeline is: coarse power-of-two sampled decode (never below the 1600 px
// target), then an exact scale to 1600 on the longest side.
class SampleSizeTest {

    @Test
    fun smallImagesAreNotSampled() {
        assertEquals(1, ImageScaler.computeInSampleSize(1024, 1024))
        assertEquals(1, ImageScaler.computeInSampleSize(1600, 900))
        assertEquals(1, ImageScaler.computeInSampleSize(1, 1))
    }

    @Test
    fun sampleSizeHalvesWithoutDroppingBelowTarget() {
        // 4000 px longest side: /2 = 2000 (>= 1600, allowed), /4 = 1000 (too small).
        assertEquals(2, ImageScaler.computeInSampleSize(4000, 3000))
        // 3200 /2 = 1600, exactly the target, still allowed.
        assertEquals(2, ImageScaler.computeInSampleSize(3200, 2400))
        // 3199 /2 = 1599, below target, so no sampling.
        assertEquals(1, ImageScaler.computeInSampleSize(3199, 2400))
        // 8000 /4 = 2000 allowed, /8 = 1000 too small.
        assertEquals(4, ImageScaler.computeInSampleSize(8000, 2000))
    }

    @Test
    fun degenerateDimensionsFallBackToOne() {
        assertEquals(1, ImageScaler.computeInSampleSize(0, 500))
        assertEquals(1, ImageScaler.computeInSampleSize(500, -1))
    }

    @Test
    fun exactScaleCapsLongestSideAt1600() {
        assertEquals(1600 to 1200, ImageScaler.scaledDimensions(2000, 1500))
        assertEquals(1200 to 1600, ImageScaler.scaledDimensions(1500, 2000))
        // At or under the cap, dimensions pass through untouched.
        assertEquals(1600 to 900, ImageScaler.scaledDimensions(1600, 900))
        assertEquals(640 to 480, ImageScaler.scaledDimensions(640, 480))
        // Extreme aspect ratios never collapse to zero.
        assertEquals(1600 to 1, ImageScaler.scaledDimensions(20000, 10))
    }
}
