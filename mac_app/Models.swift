import Foundation
import Security

enum AccessMode: String, CaseIterable, Identifiable, Codable {
    case deviceOnly
    case localWiFi

    var id: String { rawValue }

    var title: String {
        switch self {
        case .deviceOnly: return "This Mac only"
        case .localWiFi: return "Local Wi-Fi"
        }
    }

    var subtitle: String {
        switch self {
        case .deviceOnly: return "Private local access for this device."
        case .localWiFi: return "Also expose the local web/API service on trusted Wi-Fi."
        }
    }

    var bindHost: String {
        switch self {
        case .deviceOnly: return "127.0.0.1"
        case .localWiFi: return "0.0.0.0"
        }
    }

    var icon: String {
        switch self {
        case .deviceOnly: return "desktopcomputer"
        case .localWiFi: return "wifi.router"
        }
    }
}

enum ServerState: Equatable {
    case choosing
    case preparing
    case installing
    case starting
    case running
    case stopping
    case failed(String)

    var label: String {
        switch self {
        case .choosing: return "Choose access"
        case .preparing: return "Preparing"
        case .installing: return "Installing runtime"
        case .starting: return "Starting agent service"
        case .running: return "Agent service ready"
        case .stopping: return "Stopping"
        case .failed: return "Agent service offline"
        }
    }

    var isBusy: Bool {
        switch self {
        case .preparing, .installing, .starting, .stopping: return true
        default: return false
        }
    }
}

enum OllamaState: Equatable {
    case checking
    case missing
    case installing
    case starting
    case ready
    case failed(String)

    var label: String {
        switch self {
        case .checking: return "Checking Ollama"
        case .missing: return "Ollama required"
        case .installing: return "Installing Ollama"
        case .starting: return "Starting Ollama"
        case .ready: return "Ollama ready"
        case .failed: return "Ollama issue"
        }
    }

    var isBusy: Bool {
        switch self {
        case .checking, .installing, .starting: return true
        default: return false
        }
    }
}

struct OllamaModel: Identifiable, Codable, Equatable {
    var name: String
    var model: String?
    var size: Int64?
    var modifiedAt: String?
    var parameterSize: String?
    var quantization: String?

    var id: String { name }

    var displayName: String {
        name.replacingOccurrences(of: ":latest", with: "")
    }

    var detailLine: String {
        let sizeText = size.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .file) }
        return [parameterSize, quantization, sizeText].compactMap { $0 }.joined(separator: " • ")
    }

    func matches(_ candidate: String) -> Bool {
        let normalizedCandidate = candidate.replacingOccurrences(of: ":latest", with: "")
        return name == candidate
            || model == candidate
            || name.replacingOccurrences(of: ":latest", with: "") == normalizedCandidate
            || model?.replacingOccurrences(of: ":latest", with: "") == normalizedCandidate
    }
}

struct SuggestedModel: Identifiable, Equatable {
    let id: String
    let name: String
    let description: String
    let badge: String
}

enum MessageRole: String, Codable {
    case user
    case assistant
    case system
}

struct ConversationMessage: Identifiable, Codable, Equatable {
    var id = UUID()
    var role: MessageRole
    var content: String
    var createdAt = Date()
}

struct Conversation: Identifiable, Codable, Equatable {
    var id: String
    var title: String
    var project: String
    var projectPath: String?
    var messages: [ConversationMessage]
    var updatedAt: Date
}

struct WorkspaceChange: Identifiable, Codable, Equatable {
    var path: String
    var status: String
    var additions: Int
    var deletions: Int

    var id: String { path }
}

struct WorkspaceDiff: Identifiable, Codable, Equatable {
    var path: String
    var status: String
    var additions: Int
    var deletions: Int
    var oldPreview: String
    var newPreview: String
    var patch: String

    var id: String { path }
}

struct ImplementationPlan: Identifiable, Equatable {
    var id = UUID()
    var prompt: String
    var markdown: String
    var createdAt = Date()
}

struct StagedContextFile: Identifiable, Equatable {
    var id = UUID()
    var name: String
    var path: String
    var byteCount: Int
    var excerpt: String
}

struct SystemTelemetry: Codable, Equatable {
    var cpuPercent: Double
    var memoryPercent: Double
    var diskPercent: Double
    var gpuPercent: Double?
}

struct ProjectWorkspace: Identifiable, Codable, Equatable {
    var id: String
    var name: String
    var path: String
    var createdAt: Date
    var updatedAt: Date
}

enum MainSection: String, CaseIterable {
    case chat
    case history
    case tasks
    case models
    case settings
}

enum ServicePanel: Identifiable {
    case ollama
    case agent

    var id: String {
        switch self {
        case .ollama: return "ollama"
        case .agent: return "agent"
        }
    }
}

enum PromptIntent {
    case casual
    case direct
    case agentic
    case web

    var bypassesTools: Bool {
        switch self {
        case .casual, .direct: return true
        case .agentic, .web: return false
        }
    }
}

struct IntentClassifier {
    static func classify(_ text: String) -> PromptIntent {
        let res = classify_intent_cpp(text)
        switch res {
        case 1:
            return .casual
        case 2:
            return .web
        case 3:
            return .agentic
        default:
            return .direct
        }
    }
}

struct LocalAttachment: Identifiable, Equatable {
    var id = UUID()
    var name: String
    var url: URL
    var mime: String
    var byteCount: Int
    var dataURL: String
    var textExcerpt: String?
}

struct FallbackAPIConfig: Equatable {
    private static let apiKeySecretKey = "fallbackAPIKey"

    var baseURL: String
    var apiKey: String
    var model: String

    var isConfigured: Bool {
        !baseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !apiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    static func load() -> FallbackAPIConfig {
        let defaults = UserDefaults.standard
        let migratedAPIKey = LocalSecrets.string(for: apiKeySecretKey, migrateFromDefaults: true)
        return FallbackAPIConfig(
            baseURL: defaults.string(forKey: "fallbackAPIBaseURL") ?? "https://api.openai.com/v1",
            apiKey: migratedAPIKey ?? "",
            model: defaults.string(forKey: "fallbackAPIModel") ?? ""
        )
    }

    func save() {
        let defaults = UserDefaults.standard
        defaults.set(baseURL, forKey: "fallbackAPIBaseURL")
        LocalSecrets.set(apiKey.trimmingCharacters(in: .whitespacesAndNewlines), for: Self.apiKeySecretKey)
        defaults.set(model, forKey: "fallbackAPIModel")
    }
}

enum LocalSecrets {
    private static let service = "com.geocentric.native"

    static func string(for key: String, migrateFromDefaults: Bool = false) -> String? {
        if let value = keychainString(for: key) {
            return value
        }

        guard migrateFromDefaults,
              let migrated = UserDefaults.standard.string(forKey: key),
              !migrated.isEmpty
        else {
            return nil
        }

        set(migrated, for: key)
        UserDefaults.standard.removeObject(forKey: key)
        return migrated
    }

    static func set(_ value: String, for key: String) {
        guard !value.isEmpty, let data = value.data(using: .utf8) else {
            delete(key)
            return
        }

        let query = baseQuery(for: key)
        SecItemDelete(query as CFDictionary)

        var addQuery = query
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(addQuery as CFDictionary, nil)
    }

    static func delete(_ key: String) {
        SecItemDelete(baseQuery(for: key) as CFDictionary)
        UserDefaults.standard.removeObject(forKey: key)
    }

    private static func keychainString(for key: String) -> String? {
        var query = baseQuery(for: key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8),
              !value.isEmpty
        else {
            return nil
        }
        return value
    }

    private static func baseQuery(for key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]
    }
}

struct ProcessResult {
    var status: Int32
    var output: String
}

enum ProcessRunner {
    static func run(executable: String, arguments: [String], currentDirectory: URL) throws -> ProcessResult {
        let task = Process()
        let pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = arguments
        task.currentDirectoryURL = currentDirectory
        task.standardOutput = pipe
        task.standardError = pipe

        try task.run()
        task.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8) ?? ""
        return ProcessResult(status: task.terminationStatus, output: output)
    }
}
