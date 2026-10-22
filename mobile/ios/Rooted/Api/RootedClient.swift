import Foundation

// Client for the live Rooted SBR API. Every screen in the app renders responses
// from this deployed service or an honest error state. There is no mock data.
// Field names below match the live camelCase JSON, verified with curl against
// the deployed endpoints on 2026-07-01.

enum RootedAPI {
    static let baseURL = URL(string: "https://veridex-api-ubvc.onrender.com")!
    static let webBase = "https://veridex-web-phi.vercel.app"

    // Shareable receipt page on the Rooted web front end for a recovered manifest.
    static func webReceiptURL(manifestId: String) -> URL? {
        URL(string: webBase + "/r/" + RootedClient.encodeId(manifestId))
    }
}

// MARK: - Response models

struct MatchResponse: Codable, Equatable {
    let matches: [Match]
}

// Live shape note: the deployed API names the score field "similarityScore".
struct Match: Codable, Equatable {
    let manifestId: String
    let similarityScore: Double
}

struct SystemProvenance: Codable, Equatable {
    let model: String?
    let provider: String?
    let generator: String?
}

struct SoftBinding: Codable, Equatable {
    let alg: String?
    let value: String?
    let scope: String?
}

struct Manifest: Codable, Equatable {
    let manifestId: String
    let assetSha256: String
    let createdAt: String
    let systemProvenance: SystemProvenance?
    let softBindings: [SoftBinding]?
}

struct Checkpoint: Codable, Equatable {
    let epoch: Int
    let treeSize: Int
    let rootHash: String
    let signedAt: String
    let signatureB64: String
}

struct TransparencyProof: Codable, Equatable {
    let manifestId: String
    let leafIndex: Int
    let leafHash: String
    let treeSize: Int
    let rootHash: String
    let serverVerified: Bool
    let checkpoint: Checkpoint?
}

// C2PA SBR 2.4 proof-of-ingestion receipt. The JSON-LD style keys "@context"
// and "@type" are mapped through explicit CodingKeys; "@context" is an object
// of namespace names to URIs on the live service.
struct Receipt: Codable, Equatable {
    let context: [String: String]
    let type: String
    let repository: ReceiptRepository
    let anchor: ReceiptAnchor
    let verified: Bool

    enum CodingKeys: String, CodingKey {
        case context = "@context"
        case type = "@type"
        case repository
        case anchor
        case verified
    }
}

struct ReceiptRepository: Codable, Equatable {
    let uri: String
    let manifestId: String
}

struct ReceiptAnchor: Codable, Equatable {
    let uri: String
    let parameters: ReceiptAnchorParameters
}

struct ReceiptAnchorParameters: Codable, Equatable {
    let epoch: Int
}

struct LogEntry: Codable, Equatable, Identifiable {
    let leafIndex: Int
    let manifestId: String
    let leafHash: String

    var id: Int { leafIndex }
}

struct TransparencyLog: Codable, Equatable {
    let entries: [LogEntry]
    let treeSize: Int
    let rootHash: String
}

struct StatusTransparency: Codable, Equatable {
    let treeSize: Int
    let rootHash: String
}

struct ServiceStatus: Codable, Equatable {
    let service: String
    let transparency: StatusTransparency
}

// MARK: - Errors

enum RootedClientError: LocalizedError {
    case badURL(String)
    case notHTTP
    case badStatus(Int)

    var errorDescription: String? {
        switch self {
        case .badURL(let path):
            return "Could not build a request URL for \(path)."
        case .notHTTP:
            return "The Rooted API returned a non-HTTP response."
        case .badStatus(let code):
            return "The Rooted API answered with HTTP \(code)."
        }
    }
}

// MARK: - Multipart form encoding

// Built by hand so the exact bytes are testable. One file field is all the
// SBR byContent endpoint needs.
enum MultipartForm {
    static func body(
        boundary: String,
        fieldName: String,
        filename: String,
        contentType: String,
        fileData: Data
    ) -> Data {
        var data = Data()
        data.append(Data("--\(boundary)\r\n".utf8))
        data.append(Data("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(filename)\"\r\n".utf8))
        data.append(Data("Content-Type: \(contentType)\r\n\r\n".utf8))
        data.append(fileData)
        data.append(Data("\r\n--\(boundary)--\r\n".utf8))
        return data
    }
}

// MARK: - Client

struct RootedClient {
    let baseURL: URL
    private let session: URLSession

    init(baseURL: URL = RootedAPI.baseURL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    // Percent-encodes a manifest id for use as a single path segment, so the
    // colons in "urn:c2pa:..." travel as %3A exactly as the API expects.
    static func encodeId(_ id: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        return id.addingPercentEncoding(withAllowedCharacters: allowed) ?? id
    }

    // MARK: Endpoints

    // POST /matches/byContent with a multipart "file" field. The registry
    // answers with zero or more matches; zero is an honest "not found".
    func matchByContent(imageData: Data, filename: String) async throws -> MatchResponse {
        guard let url = URL(string: baseURL.absoluteString + "/matches/byContent") else {
            throw RootedClientError.badURL("matches/byContent")
        }
        let boundary = "rooted-boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = MultipartForm.body(
            boundary: boundary,
            fieldName: "file",
            filename: filename,
            contentType: "image/jpeg",
            fileData: imageData
        )
        return try await send(request)
    }

    func manifest(id: String) async throws -> Manifest {
        try await get(path: "manifests/\(Self.encodeId(id))")
    }

    func receipt(id: String) async throws -> Receipt {
        try await get(path: "manifests/\(Self.encodeId(id))/receipts")
    }

    func proof(id: String) async throws -> TransparencyProof {
        try await get(path: "transparency/proof/\(Self.encodeId(id))")
    }

    func log() async throws -> TransparencyLog {
        try await get(path: "transparency/log")
    }

    func status() async throws -> ServiceStatus {
        try await get(path: "status")
    }

    // MARK: Plumbing

    private func get<T: Decodable>(path: String) async throws -> T {
        // The path is already percent-encoded where it needs to be, so the URL
        // is assembled from strings rather than appendingPathComponent, which
        // would re-encode the percent signs.
        guard let url = URL(string: baseURL.absoluteString + "/" + path) else {
            throw RootedClientError.badURL(path)
        }
        return try await send(URLRequest(url: url))
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw RootedClientError.notHTTP
        }
        guard (200 ..< 300).contains(http.statusCode) else {
            throw RootedClientError.badStatus(http.statusCode)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
