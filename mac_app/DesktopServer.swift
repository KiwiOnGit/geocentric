import Foundation
import Combine
import AppKit

final class DesktopServer: ObservableObject {
    static let shared = DesktopServer()

    @Published var mode: AccessMode?
    @Published var state: ServerState = .choosing
    @Published var statusText = "Choose how Geocentric should be hosted for this launch."
    @Published var logs: [String] = []
    @Published var serverPort = 8000
    @Published var localURL: URL?
    @Published var networkURL: URL?

    private let basePort = 8000
    private let logLimit = 240
    private let worker = DispatchQueue(label: "com.geocentric.desktop.server", qos: .userInitiated)
    private var pythonProcess: Process?
    private var outputPipe: Pipe?
    private var intentionalStop = false
    private var lastMode: AccessMode?
    private var healthTimer: DispatchSourceTimer?

    private init() {}

    var isReady: Bool {
        if case .running = state { return true }
        return false
    }

    var isUsable: Bool {
        isReady && localURL != nil
    }

    func startIfNeeded(mode preferredMode: AccessMode = .deviceOnly) {
        if isUsable || state.isBusy { return }
        start(mode: mode ?? lastMode ?? preferredMode)
    }

    func waitUntilReady(timeout: TimeInterval = 120, startIfNeeded shouldStart: Bool = true) async -> URL? {
        if isReady, let localURL {
            return localURL
        }
        if shouldStart {
            await MainActor.run {
                self.startIfNeeded()
            }
        }

        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if isReady, let localURL {
                return localURL
            }

            if Task.isCancelled {
                return nil
            }

            try? await Task.sleep(nanoseconds: 500_000_000)
        }

        return isReady ? localURL : nil
    }

    func start(mode: AccessMode) {
        terminateServer(reset: false, updateUI: false)
        intentionalStop = false
        lastMode = mode

        DispatchQueue.main.async {
            self.mode = mode
            self.state = .preparing
            self.statusText = "Preparing the local agent service..."
            self.logs.removeAll()
            self.localURL = nil
            self.networkURL = nil
        }

        worker.async { [weak self] in
            self?.bootstrapAndLaunch(mode: mode)
        }
    }

    func restart() {
        guard let mode = mode ?? lastMode else { return }
        start(mode: mode)
    }

    func chooseAgain() {
        terminateServer(reset: true)
    }

    func terminateServer(reset: Bool = false, updateUI: Bool = true) {
        intentionalStop = true
        healthTimer?.cancel()
        healthTimer = nil
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        outputPipe = nil

        if let process = pythonProcess, process.isRunning {
            process.terminationHandler = nil
            if updateUI {
                DispatchQueue.main.async {
                    self.state = .stopping
                    self.statusText = "Stopping the local agent service..."
                }
            }
            process.terminate()
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 1.0) {
                if process.isRunning {
                    process.interrupt()
                }
            }
        } else if let process = pythonProcess {
            process.terminationHandler = nil
        }

        pythonProcess = nil

        if reset {
            DispatchQueue.main.async {
                self.mode = nil
                self.state = .choosing
                self.statusText = "Choose how Geocentric should be hosted for this launch."
                self.localURL = nil
                self.networkURL = nil
                self.logs.removeAll()
            }
        }
    }

    private func bootstrapAndLaunch(mode: AccessMode) {
        do {
            guard let resourceRoot = locateResourceRoot() else {
                throw appError("Could not find bundled Geocentric server resources.")
            }

            let supportRoot = try applicationSupportRoot()
            let port = nextAvailablePort(startingAt: basePort)

            publish {
                self.serverPort = port
                self.statusText = "Preparing app data in Application Support..."
            }

            try FileManager.default.createDirectory(at: supportRoot, withIntermediateDirectories: true)
            let pythonExec = try ensurePythonRuntime(resourceRoot: resourceRoot, supportRoot: supportRoot)

            publish {
                self.state = .starting
                self.statusText = "Starting local agent service on \(mode.bindHost):\(port)..."
            }

            try launchServer(
                pythonExec: pythonExec,
                resourceRoot: resourceRoot,
                supportRoot: supportRoot,
                mode: mode,
                port: port
            )

            pollUntilReady(port: port, mode: mode, deadline: Date().addingTimeInterval(90))
        } catch {
            publishFailure(error.localizedDescription)
        }
    }

    private func ensurePythonRuntime(resourceRoot: URL, supportRoot: URL) throws -> String {
        let fm = FileManager.default
        let runtimeRoot = supportRoot.appendingPathComponent("Runtime", isDirectory: true)
        let venvRoot = runtimeRoot.appendingPathComponent("venv", isDirectory: true)
        let appPython = venvRoot.appendingPathComponent("bin/python3")
        let devPython = resourceRoot.appendingPathComponent(".venv/bin/python3")

        try fm.createDirectory(at: runtimeRoot, withIntermediateDirectories: true)

        if Bundle.main.bundleURL.pathExtension != "app",
           fm.fileExists(atPath: devPython.path),
           pythonHasRequiredPackages(devPython.path) {
            appendLog("Using development Python environment at \(devPython.path)")
            return devPython.path
        }

        let basePython = try compatiblePythonExecutable()

        if fm.fileExists(atPath: appPython.path), !pythonVersionIsSupported(appPython.path) {
            appendLog("Replacing incompatible Python runtime at \(venvRoot.path)")
            try? fm.removeItem(at: venvRoot)
        }

        if !fm.fileExists(atPath: appPython.path) {
            publish {
                self.state = .installing
                self.statusText = "Creating a private Python runtime..."
            }
            try runProcess(
                executable: basePython,
                arguments: ["-m", "venv", venvRoot.path],
                currentDirectory: supportRoot
            )
        }

        let requirements = resourceRoot.appendingPathComponent("requirements.txt")
        guard fm.fileExists(atPath: requirements.path) else {
            appendLog("No requirements.txt found in \(resourceRoot.path); continuing with existing Python runtime.")
            return appPython.path
        }

        let marker = runtimeRoot.appendingPathComponent("requirements.marker")
        let requirementsData = try Data(contentsOf: requirements)
        let markerValue = requirementsData.base64EncodedString()
        let installedMarker = (try? String(contentsOf: marker, encoding: .utf8)) ?? ""

        if installedMarker != markerValue || !pythonHasRequiredPackages(appPython.path) {
            publish {
                self.state = .installing
                self.statusText = "Installing local agent service dependencies..."
            }

            try runProcess(
                executable: appPython.path,
                arguments: ["-m", "pip", "install", "--upgrade", "pip"],
                currentDirectory: supportRoot
            )
            try runProcess(
                executable: appPython.path,
                arguments: ["-m", "pip", "install", "-r", requirements.path],
                currentDirectory: supportRoot
            )
            try markerValue.write(to: marker, atomically: true, encoding: .utf8)
        }

        return appPython.path
    }

    private func compatiblePythonExecutable() throws -> String {
        let fm = FileManager.default
        let candidates = [
            "/opt/homebrew/bin/python3.12",
            "/usr/local/bin/python3.12",
            "/usr/bin/python3.12",
            "/opt/homebrew/bin/python3.11",
            "/usr/local/bin/python3.11",
            "/usr/bin/python3.11",
            "/opt/homebrew/bin/python3.10",
            "/usr/local/bin/python3.10",
            "/usr/bin/python3.10",
            "/opt/homebrew/bin/python3.9",
            "/usr/local/bin/python3.9",
            "/usr/bin/python3"
        ]

        for candidate in candidates where fm.isExecutableFile(atPath: candidate) {
            if pythonVersionIsSupported(candidate) {
                appendLog("Using Python runtime creator at \(candidate)")
                return candidate
            }
            appendLog("Skipping incompatible Python at \(candidate)")
        }

        throw appError("Geocentric needs Python 3.9 through 3.12 to install its local agent service. Install Python 3.12 and restart the app.")
    }

    private func pythonVersionIsSupported(_ pythonPath: String) -> Bool {
        guard let version = pythonVersion(pythonPath) else { return false }
        return version.major == 3 && (9...12).contains(version.minor)
    }

    private func pythonVersion(_ pythonPath: String) -> (major: Int, minor: Int)? {
        let task = Process()
        let pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: pythonPath)
        task.arguments = ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]
        task.standardOutput = pipe
        task.standardError = Pipe()

        do {
            try task.run()
            task.waitUntilExit()
        } catch {
            return nil
        }

        guard task.terminationStatus == 0 else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let text = String(data: data, encoding: .utf8) else { return nil }
        let parts = text.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: ".")
        guard parts.count == 2, let major = Int(parts[0]), let minor = Int(parts[1]) else { return nil }
        return (major, minor)
    }

    private func launchServer(
        pythonExec: String,
        resourceRoot: URL,
        supportRoot: URL,
        mode: AccessMode,
        port: Int
    ) throws {
        let task = Process()
        let pipe = Pipe()
        var environment = ProcessInfo.processInfo.environment
        let existingPythonPath = environment["PYTHONPATH"]
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONPATH"] = [resourceRoot.path, existingPythonPath]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: ":")

        let modelDir = preferredModelDirectory(resourceRoot: resourceRoot, supportRoot: supportRoot)
        var arguments = [
            "-m", "geocentric.server",
            "--host", mode.bindHost,
            "--port", String(port)
        ]
        if let modelDir {
            arguments.append(contentsOf: ["--model_dir", modelDir.path])
        }

        task.executableURL = URL(fileURLWithPath: pythonExec)
        task.arguments = arguments
        task.currentDirectoryURL = supportRoot
        task.environment = environment
        task.standardOutput = pipe
        task.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            self?.appendLog(text)
        }

        task.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self, !self.intentionalStop else { return }
                self.state = .failed("Agent service stopped with exit code \(process.terminationStatus).")
                self.statusText = "The local agent service stopped unexpectedly. Direct Ollama chat can still work."
            }
        }

        try task.run()
        pythonProcess = task
        outputPipe = pipe
        appendLog("Launched: \(pythonExec) \(arguments.joined(separator: " "))")
    }

    private func pollUntilReady(port: Int, mode: AccessMode, deadline: Date) {
        let statusURL = URL(string: "http://127.0.0.1:\(port)/api/status")!
        var request = URLRequest(url: statusURL)
        request.timeoutInterval = 1.5

        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            guard let self else { return }

            if let http = response as? HTTPURLResponse, (200..<500).contains(http.statusCode) {
                self.publishReady(port: port, mode: mode)
                return
            }

            if Date() > deadline {
                self.publishFailure("The agent service did not become ready in time. Direct Ollama chat can still work.")
                return
            }

            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 0.6) {
                self.pollUntilReady(port: port, mode: mode, deadline: deadline)
            }
        }.resume()
    }

    private func publishReady(port: Int, mode: AccessMode) {
        let local = URL(string: "http://127.0.0.1:\(port)")!
        let lanAddress = localIPAddress()
        let network = lanAddress.flatMap { URL(string: "http://\($0):\(port)") }

        publish {
            self.localURL = local
            self.networkURL = mode == .localWiFi ? network : nil
            self.state = .running
            if mode == .localWiFi, let network {
                self.statusText = "Agent service ready on this Mac and Wi-Fi: \(network.absoluteString)"
            } else {
                self.statusText = "Agent service ready privately on this Mac."
            }
        }
        startHealthPolling()
    }

    private func startHealthPolling() {
        healthTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: worker)
        timer.schedule(deadline: .now() + 3, repeating: .seconds(5))
        timer.setEventHandler { [weak self] in
            self?.pollHealth()
        }
        healthTimer = timer
        timer.resume()
    }

    private func pollHealth() {
        guard let localURL else { return }
        let statusURL = localURL.appendingPathComponent("api/status")
        var request = URLRequest(url: statusURL)
        request.timeoutInterval = 2

        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: request) { _, response, _ in
            if let http = response as? HTTPURLResponse, (200..<500).contains(http.statusCode) {
                ok = true
            }
            semaphore.signal()
        }.resume()
        if semaphore.wait(timeout: .now() + 3) == .timedOut {
            ok = false
        }

        DispatchQueue.main.async {
            if ok {
                self.state = .running
                if self.mode == .localWiFi, let network = self.networkURL {
                    self.statusText = "Agent service ready on this Mac and Wi-Fi: \(network.absoluteString)"
                } else {
                    self.statusText = "Agent service ready privately on this Mac."
                }
            } else if self.pythonProcess?.isRunning == true {
                self.state = .failed("Agent service is not responding.")
                self.statusText = "Agent service is running but not responding."
                self.localURL = nil
                self.networkURL = nil
            } else {
                self.state = .failed("Agent service is offline.")
                self.statusText = "Agent service is offline."
                self.localURL = nil
                self.networkURL = nil
            }
        }
    }

    private func runProcess(executable: String, arguments: [String], currentDirectory: URL) throws {
        appendLog("$ \(executable) \(arguments.joined(separator: " "))")
        let result = try ProcessRunner.run(executable: executable, arguments: arguments, currentDirectory: currentDirectory)
        if !result.output.isEmpty {
            appendLog(result.output)
        }
        if result.status != 0 {
            throw appError("\(URL(fileURLWithPath: executable).lastPathComponent) exited with code \(result.status).")
        }
    }

    private func pythonHasRequiredPackages(_ pythonPath: String) -> Bool {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: pythonPath)
        task.arguments = ["-c", "import fastapi, uvicorn, torch, cryptography, psutil"]
        task.standardOutput = Pipe()
        task.standardError = Pipe()
        do {
            try task.run()
            task.waitUntilExit()
            return task.terminationStatus == 0
        } catch {
            return false
        }
    }

    private func locateResourceRoot() -> URL? {
        let fm = FileManager.default
        let cwd = URL(fileURLWithPath: fm.currentDirectoryPath)
        var candidates: [URL] = []

        if let resourceURL = Bundle.main.resourceURL {
            candidates.append(resourceURL)
        }
        if let executableURL = Bundle.main.executableURL {
            let executableDir = executableURL.deletingLastPathComponent()
            candidates.append(executableDir)
            candidates.append(executableDir.deletingLastPathComponent())
            candidates.append(executableDir.deletingLastPathComponent().deletingLastPathComponent())
        }

        candidates.append(Bundle.main.bundleURL.appendingPathComponent("Contents/Resources"))
        candidates.append(cwd)
        candidates.append(cwd.deletingLastPathComponent())
        candidates.append(fm.homeDirectoryForCurrentUser.appendingPathComponent("geocentric"))

        var seen = Set<String>()
        for candidate in candidates {
            let standardized = candidate.standardizedFileURL
            guard seen.insert(standardized.path).inserted else { continue }
            let server = standardized.appendingPathComponent("geocentric/server.py")
            if fm.fileExists(atPath: server.path) {
                appendLog("Using resources at \(standardized.path)")
                return standardized
            }
        }
        return nil
    }

    private func applicationSupportRoot() throws -> URL {
        guard let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            throw appError("Could not resolve Application Support.")
        }
        return base.appendingPathComponent("Geocentric", isDirectory: true)
    }

    private func preferredModelDirectory(resourceRoot: URL, supportRoot: URL) -> URL? {
        let fm = FileManager.default
        let candidates = [
            supportRoot.appendingPathComponent("runs/geocentric2_1"),
            supportRoot.appendingPathComponent("models/geocentric2_1"),
            resourceRoot.appendingPathComponent("runs/geocentric2_1"),
            resourceRoot.appendingPathComponent("models/geocentric2_1")
        ]
        return candidates.first { fm.fileExists(atPath: $0.path) }
    }

    private func nextAvailablePort(startingAt port: Int) -> Int {
        for candidate in port...(port + 100) {
            if portIsAvailable(candidate) {
                return candidate
            }
        }
        return port
    }

    private func portIsAvailable(_ port: Int) -> Bool {
        let sock = socket(AF_INET, SOCK_STREAM, 0)
        if sock < 0 { return false }
        defer { close(sock) }

        var yes: Int32 = 1
        setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(port).bigEndian
        address.sin_addr = in_addr(s_addr: INADDR_ANY)

        let result = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }

    private func localIPAddress() -> String? {
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let firstAddress = ifaddr else { return nil }
        defer { freeifaddrs(ifaddr) }

        var addresses: [(name: String, ip: String)] = []
        var pointer: UnsafeMutablePointer<ifaddrs>? = firstAddress

        while let interface = pointer?.pointee {
            defer { pointer = interface.ifa_next }
            guard let socketAddress = interface.ifa_addr else { continue }
            guard socketAddress.pointee.sa_family == UInt8(AF_INET) else { continue }

            let flags = Int32(interface.ifa_flags)
            let isUp = (flags & IFF_UP) == IFF_UP
            let isRunning = (flags & IFF_RUNNING) == IFF_RUNNING
            let isLoopback = (flags & IFF_LOOPBACK) == IFF_LOOPBACK
            guard isUp && isRunning && !isLoopback else { continue }

            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let result = getnameinfo(
                socketAddress,
                socklen_t(socketAddress.pointee.sa_len),
                &hostname,
                socklen_t(hostname.count),
                nil,
                0,
                NI_NUMERICHOST
            )

            if result == 0 {
                addresses.append((String(cString: interface.ifa_name), String(cString: hostname)))
            }
        }

        return addresses.first(where: { $0.name.hasPrefix("en") })?.ip ?? addresses.first?.ip
    }

    private func appendLog(_ text: String) {
        let lines = text
            .replacingOccurrences(of: "\r", with: "\n")
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)

        guard !lines.isEmpty else { return }
        DispatchQueue.main.async {
            self.logs.append(contentsOf: lines)
            if self.logs.count > self.logLimit {
                self.logs.removeFirst(self.logs.count - self.logLimit)
            }
        }
    }

    private func publish(_ update: @escaping () -> Void) {
        DispatchQueue.main.async(execute: update)
    }

    private func publishFailure(_ message: String) {
        publish {
            self.state = .failed(message)
            self.statusText = message
        }
        appendLog("Error: \(message)")
    }

    private func appError(_ message: String) -> NSError {
        NSError(domain: "GeocentricDesktop", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
