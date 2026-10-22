# Veridex Verify (Android)

The physical-world verifier for [Veridex](YOUR_VERIDEX_SITE_URL). Pick an image,
photograph one, or share one from any app; the live Veridex SBR API recovers its stripped C2PA
provenance by invisible watermark or perceptual hash, and the app shows the recovered manifest
with the live Merkle inclusion proof.

## Build

Requires JDK 17+ (CI pins Temurin 21; local builds verified on OpenJDK 24) and an Android SDK
with `platforms;android-36` and `build-tools;36.0.0`. Point `local.properties` at your SDK
(`sdk.dir=/path/to/sdk`); the file is gitignored.

```
./gradlew assembleDebug          # APK at app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest      # unit tests
```

Toolchain: Gradle 8.14 (wrapper committed), AGP 8.13.2, Kotlin 2.2.21, Compose BOM 2026.06.01,
minSdk 26, target/compileSdk 36.

## Share target

From any app (gallery, browser, messenger), tap Share on an image and choose Veridex Verify.
The image lands directly in the verify flow: downscaled to 1600 px, uploaded to
`POST /matches/byContent`, and the top match is expanded with the manifest, the C2PA SBR 2.4
receipt, and the live transparency proof. The emerald VERIFIED badge appears only when the
proof endpoint reports `serverVerified: true`.

## Honesty note

There is no mock data in this app. Every screen renders a live response from
`YOUR_VERIDEX_API_URL` or an honest error state (no match, network error, HTTP
detail from the API). The unit-test JSON fixtures are byte-for-byte captures of real live
responses, taken by curl and dated in the test source. Provenance proves origin, not truth.

## Distribution

Plan: Google Play internal app sharing for judge-facing installs (upload the debug or a signed
release APK, share the link; no review cycle needed).
