import Foundation
import Combine
import AppKit

private let ollamaDownloadURL = URL(string: "https://ollama.com/download/Ollama-darwin.zip")!
private let ollamaAPIBase = URL(string: "http://127.0.0.1:11434")!

struct OllamaTagsResponse: Decodable {
    struct Model: Decodable {
        struct Details: Decodable {
            var parameter_size: String?
            var quantization_level: String?
        }
        var name: String
        var model: String?
        var modified_at: String?
        var size: Int64?
        var details: Details?
    }
    var models: [Model]
}

final class OllamaManager: ObservableObject {
    static let shared = OllamaManager()

    @Published var state: OllamaState = .checking
    @Published var statusText = "Checking Ollama..."
    @Published var installedModels: [OllamaModel] = []
    @Published var selectedModel: String = UserDefaults.standard.string(forKey: "selectedOllamaModel") ?? ""
    @Published var pullingModel: String?
    @Published var deletingModel: String?
    @Published var logs: [String] = []

    let suggestedModels: [SuggestedModel] = [
        SuggestedModel(id: "qwen3-coder", name: "Qwen3 Coder", description: "Best default for agentic coding and app creation.", badge: "Coding"),
        SuggestedModel(id: "gpt-oss:20b", name: "GPT OSS 20B", description: "Strong general assistant for local planning and reasoning.", badge: "General"),
        SuggestedModel(id: "gemma3", name: "Gemma 3", description: "Balanced model for fast everyday local tasks.", badge: "Fast"),
        SuggestedModel(id: "llama3.2", name: "Llama 3.2", description: "Lightweight model for quick on-device chat.", badge: "Small"),
        SuggestedModel(id: "deepseek-r1", name: "DeepSeek R1", description: "Reasoning-heavy option for harder debugging sessions.", badge: "Reasoning")
    ]

    private let worker = DispatchQueue(label: "com.geocentric.desktop.ollama", qos: .userInitiated)
    private var ownedServerProcess: Process?
    private var pollTimer: DispatchSourceTimer?

    private init() {}

    var isReady: Bool {
        if case .ready = state { return true }
        return false
    }

    var hasSelectedInstalledModel: Bool {
        installedModels.contains { $0.matches(selectedModel) }
    }

    func bootstrap() {
        refreshModels(startIfNeeded: true)
        startStatusPolling()
    }

    func refreshModels(startIfNeeded: Bool = true) {
        publish {
            if self.installedModels.isEmpty {
                self.state = .checking
                self.statusText = "Checking Ollama..."
            }
        }

        worker.async { [weak self] in
            guard let self else { return }
            if startIfNeeded {
                self.startOllamaIfPossible()
            }
            self.fetchModels()
        }
    }

    func installOllama() {
        publish {
            self.state = .installing
            self.statusText = "Downloading Ollama for macOS..."
            self.logs.removeAll()
        }

        let downloadURL = ollamaDownloadURL
        URLSession.shared.downloadTask(with: downloadURL) { [weak self] tempURL, _, error in
            guard let self else { return }
            do {
                if let error {
                    throw error
                }
                guard let tempURL else {
                    throw self.appError("Ollama download did not produce a file.")
                }

                let fm = FileManager.default
                let tempRoot = fm.temporaryDirectory.appendingPathComponent("GeocentricOllama-\(UUID().uuidString)", isDirectory: true)
                let zipPath = tempRoot.appendingPathComponent("Ollama-darwin.zip")
                let support = try self.ollamaSupportRoot()
                let destination = support.appendingPathComponent("Ollama.app", isDirectory: true)

                try fm.createDirectory(at: tempRoot, withIntermediateDirectories: true)
                try fm.createDirectory(at: support, withIntermediateDirectories: true)
                try fm.copyItem(at: tempURL, to: zipPath)

                self.publish {
                    self.statusText = "Installing Ollama into Geocentric Application Support..."
                }

                let unzip = try ProcessRunner.run(
                    executable: "/usr/bin/unzip",
                    arguments: ["-q", zipPath.path, "-d", tempRoot.path],
                    currentDirectory: tempRoot
                )
                if unzip.status != 0 {
                    throw self.appError(unzip.output.isEmpty ? "Failed to unzip Ollama." : unzip.output)
                }

                let unpackedApp = tempRoot.appendingPathComponent("Ollama.app", isDirectory: true)
                if fm.fileExists(atPath: destination.path) {
                    try fm.removeItem(at: destination)
                }
                try fm.moveItem(at: unpackedApp, to: destination)
                try? fm.removeItem(at: tempRoot)

                self.appendLog("Installed Ollama at \(destination.path)")
                self.startOllamaIfPossible()
                self.fetchModels()
            } catch {
                self.publish {
                    self.state = .failed(error.localizedDescription)
                    self.statusText = error.localizedDescription
                }
            }
        }.resume()
    }

    func downloadModel(_ modelID: String) {
        let normalizedModelID = modelID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard pullingModel == nil, deletingModel == nil, !normalizedModelID.isEmpty else { return }
        publish {
            self.pullingModel = normalizedModelID
            self.state = .ready
            self.statusText = "Downloading \(normalizedModelID)..."
        }

        worker.async { [weak self] in
            guard let self else { return }
            do {
                self.startOllamaIfPossible()
                if let cli = self.locateOllamaCLI() {
                    let result = try ProcessRunner.run(
                        executable: cli.path,
                        arguments: ["pull", normalizedModelID],
                        currentDirectory: self.applicationSupportRoot()
                    )
                    if !result.output.isEmpty {
                        self.appendLog(result.output)
                    }
                    if result.status != 0 {
                        throw self.appError(result.output.isEmpty ? "ollama pull failed." : result.output)
                    }
                } else {
                    try self.pullModelViaAPI(normalizedModelID)
                }

                self.fetchModels(select: normalizedModelID)
            } catch {
                self.publish {
                    self.state = .failed(error.localizedDescription)
                    self.statusText = error.localizedDescription
                    self.pullingModel = nil
                }
            }
        }
    }

    func deleteModel(_ modelName: String) {
        guard pullingModel == nil, deletingModel == nil, !modelName.isEmpty else { return }
        publish {
            self.deletingModel = modelName
            self.statusText = "Deleting \(modelName)..."
        }

        worker.async { [weak self] in
            guard let self else { return }
            do {
                self.startOllamaIfPossible()
                if let cli = self.locateOllamaCLI() {
                    let result = try ProcessRunner.run(
                        executable: cli.path,
                        arguments: ["rm", modelName],
                        currentDirectory: self.applicationSupportRoot()
                    )
                    if !result.output.isEmpty {
                        self.appendLog(result.output)
                    }
                    if result.status != 0 {
                        throw self.appError(result.output.isEmpty ? "ollama rm failed." : result.output)
                    }
                } else {
                    try self.deleteModelViaAPI(modelName)
                }

                self.fetchModels()
            } catch {
                self.publish {
                    self.state = .failed(error.localizedDescription)
                    self.statusText = error.localizedDescription
                    self.deletingModel = nil
                }
            }
        }
    }

    func selectModel(_ model: String) {
        publish {
            self.selectedModel = model
            UserDefaults.standard.set(model, forKey: "selectedOllamaModel")
            self.statusText = "Selected \(model)"
        }
    }

    func stopOwnedServer() {
        pollTimer?.cancel()
        pollTimer = nil
        if let process = ownedServerProcess, process.isRunning {
            process.terminate()
        }
        ownedServerProcess = nil
    }

    private func startStatusPolling() {
        pollTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: worker)
        timer.schedule(deadline: .now() + 4, repeating: .seconds(8))
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            if self.pullingModel == nil {
                self.fetchModels()
            }
        }
        pollTimer = timer
        timer.resume()
    }

    private func startOllamaIfPossible() {
        if serviceResponds() {
            return
        }

        publish {
            self.state = .starting
            self.statusText = "Starting Ollama..."
        }

        if let app = locateOllamaApp() {
            _ = try? ProcessRunner.run(
                executable: "/usr/bin/open",
                arguments: [app.path, "--args", "hidden"],
                currentDirectory: applicationSupportRoot()
            )
        } else if let cli = locateOllamaCLI() {
            let task = Process()
            task.executableURL = cli
            task.arguments = ["serve"]
            task.currentDirectoryURL = applicationSupportRoot()
            task.standardOutput = Pipe()
            task.standardError = Pipe()
            try? task.run()
            ownedServerProcess = task
        } else {
            publish {
                self.state = .missing
                self.statusText = "Ollama is required before you can chat or download local models."
            }
            return
        }

        let deadline = Date().addingTimeInterval(30)
        while Date() < deadline {
            if serviceResponds() {
                return
            }
            Thread.sleep(forTimeInterval: 0.5)
        }
    }

    private func fetchModels(select: String? = nil) {
        do {
            guard serviceResponds() else {
                let foundOllama = locateOllamaApp() != nil || locateOllamaCLI() != nil
                publish {
                    self.state = foundOllama ? .failed("Ollama is installed but not responding.") : .missing
                    self.statusText = foundOllama ? "Ollama is installed but not responding." : "Ollama is required before you can chat."
                    self.pullingModel = nil
                    self.deletingModel = nil
                    self.installedModels = []
                }
                return
            }

            let tagsURL = ollamaAPIBase.appendingPathComponent("api/tags")
            let data = try fetchData(from: tagsURL, timeout: 3)
            let decoded = try JSONDecoder().decode(OllamaTagsResponse.self, from: data)
            let models = decoded.models.map {
                OllamaModel(
                    name: $0.name,
                    model: $0.model,
                    size: $0.size,
                    modifiedAt: $0.modified_at,
                    parameterSize: $0.details?.parameter_size,
                    quantization: $0.details?.quantization_level
                )
            }.sorted {
                if $0.name == selectedModel { return true }
                if $1.name == selectedModel { return false }
                return $0.displayName.localizedCaseInsensitiveCompare($1.displayName) == .orderedAscending
            }

            publish {
                if self.installedModels != models {
                    self.installedModels = models
                }
                if let select, let matched = models.first(where: { $0.matches(select) }) {
                    self.selectedModel = matched.name
                    UserDefaults.standard.set(matched.name, forKey: "selectedOllamaModel")
                } else if self.selectedModel.isEmpty || !models.contains(where: { $0.matches(self.selectedModel) }) {
                    self.selectedModel = models.first?.name ?? ""
                    if !self.selectedModel.isEmpty {
                        UserDefaults.standard.set(self.selectedModel, forKey: "selectedOllamaModel")
                    }
                }
                self.state = .ready
                self.statusText = models.isEmpty ? "Ollama is ready. Download a model to begin." : "\(models.count) Ollama model\(models.count == 1 ? "" : "s") available."
                self.pullingModel = nil
                self.deletingModel = nil
            }
        } catch {
            publish {
                self.state = .failed(error.localizedDescription)
                self.statusText = error.localizedDescription
                self.pullingModel = nil
                self.deletingModel = nil
            }
        }
    }

    private func pullModelViaAPI(_ modelID: String) throws {
        let url = ollamaAPIBase.appendingPathComponent("api/pull")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 3600
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "model": modelID,
            "stream": false
        ])

        let semaphore = DispatchSemaphore(value: 0)
        var resultError: Error?
        URLSession.shared.dataTask(with: request) { _, response, error in
            if let error {
                resultError = error
            } else if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                resultError = self.appError("Ollama returned HTTP \(http.statusCode) while pulling \(modelID).")
            }
            semaphore.signal()
        }.resume()
        if semaphore.wait(timeout: .now() + 3605) == .timedOut {
            throw appError("Ollama model download timed out.")
        }

        if let resultError {
            throw resultError
        }
    }

    private func deleteModelViaAPI(_ modelName: String) throws {
        let url = ollamaAPIBase.appendingPathComponent("api/delete")
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["model": modelName])

        let semaphore = DispatchSemaphore(value: 0)
        var resultError: Error?
        URLSession.shared.dataTask(with: request) { _, response, error in
            if let error {
                resultError = error
            } else if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                resultError = self.appError("Ollama returned HTTP \(http.statusCode) while deleting \(modelName).")
            }
            semaphore.signal()
        }.resume()

        if semaphore.wait(timeout: .now() + 65) == .timedOut {
            throw appError("Ollama model deletion timed out.")
        }
        if let resultError {
            throw resultError
        }
    }

    private func serviceResponds() -> Bool {
        let tagsURL = ollamaAPIBase.appendingPathComponent("api/tags")
        var request = URLRequest(url: tagsURL)
        request.timeoutInterval = 0.8

        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: request) { _, response, _ in
            if let http = response as? HTTPURLResponse, (200..<500).contains(http.statusCode) {
                ok = true
            }
            semaphore.signal()
        }.resume()
        if semaphore.wait(timeout: .now() + 2) == .timedOut {
            return false
        }
        return ok
    }

    private func fetchData(from url: URL, timeout: TimeInterval) throws -> Data {
        var request = URLRequest(url: url)
        request.timeoutInterval = timeout

        let semaphore = DispatchSemaphore(value: 0)
        var resultData: Data?
        var resultError: Error?

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let error {
                resultError = error
            } else if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                resultError = self.appError("Ollama returned HTTP \(http.statusCode).")
            } else {
                resultData = data
            }
            semaphore.signal()
        }.resume()

        if semaphore.wait(timeout: .now() + timeout + 1) == .timedOut {
            throw appError("Ollama request timed out.")
        }
        if let resultError {
            throw resultError
        }
        guard let resultData else {
            throw appError("Ollama returned an empty response.")
        }
        return resultData
    }

    private func locateOllamaApp() -> URL? {
        let fm = FileManager.default
        let candidates = [
            applicationSupportRoot().appendingPathComponent("Ollama/Ollama.app", isDirectory: true),
            URL(fileURLWithPath: "/Applications/Ollama.app", isDirectory: true)
        ]
        return candidates.first { fm.fileExists(atPath: $0.path) }
    }

    private func locateOllamaCLI() -> URL? {
        let fm = FileManager.default
        let candidates = [
            applicationSupportRoot().appendingPathComponent("Ollama/Ollama.app/Contents/Resources/ollama"),
            URL(fileURLWithPath: "/Applications/Ollama.app/Contents/Resources/ollama"),
            URL(fileURLWithPath: "/usr/local/bin/ollama"),
            URL(fileURLWithPath: "/opt/homebrew/bin/ollama")
        ]
        return candidates.first { fm.isExecutableFile(atPath: $0.path) }
    }

    private func ollamaSupportRoot() throws -> URL {
        let root = applicationSupportRoot().appendingPathComponent("Ollama", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private func applicationSupportRoot() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Geocentric", isDirectory: true)
    }

    private func appendLog(_ text: String) {
        let lines = text
            .replacingOccurrences(of: "\r", with: "\n")
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
        guard !lines.isEmpty else { return }
        publish {
            self.logs.append(contentsOf: lines)
            if self.logs.count > 180 {
                self.logs.removeFirst(self.logs.count - 180)
            }
        }
    }

    private func publish(_ update: @escaping () -> Void) {
        DispatchQueue.main.async(execute: update)
    }

    private func appError(_ message: String) -> NSError {
        NSError(domain: "GeocentricOllama", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
