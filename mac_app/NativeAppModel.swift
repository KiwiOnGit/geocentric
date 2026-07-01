import Foundation
import Combine
import AppKit
import Darwin

final class NativeAppModel: ObservableObject, @unchecked Sendable {
    static weak var sharedReference: NativeAppModel?

    @Published var selectedSection: MainSection = .chat
    @Published var projects: [ProjectWorkspace] = []
    @Published var selectedProjectID: String?
    @Published var conversations: [Conversation] = []
    @Published var selectedConversationID: String?
    @Published var prompt = ""
    @Published var isSending = false
    @Published var statusText = "Ready"
    @Published var showModels = false
    @Published var activeServicePanel: ServicePanel?
    @Published var agentMode = true
    @Published var webSearch = false
    @Published var pendingAttachments: [LocalAttachment] = []
    @Published var fallbackAPI = FallbackAPIConfig.load()
    @Published var sidebarVisible = true
    @Published var conversationSearchText = ""
    @Published var activeAgentProgress = ""
    @Published var activeAgentRoadmap = ""
    @Published var activeAgentChanges: [WorkspaceChange] = []
    @Published var activeAgentDiffs: [WorkspaceDiff] = []
    @Published var stagedContextFiles: [StagedContextFile] = []
    @Published var pendingImplementationPlan: ImplementationPlan?
    @Published var telemetry = SystemTelemetry(cpuPercent: 0, memoryPercent: 0, diskPercent: 0, gpuPercent: nil)
    @Published var lastAgentJobID: String?
    @Published var animatedBackgroundEnabled: Bool = true {
        didSet {
            UserDefaults.standard.set(animatedBackgroundEnabled, forKey: "animatedBackgroundEnabled")
        }
    }
    @Published var customAccentColor: String = "blue" {
        didSet {
            UserDefaults.standard.set(customAccentColor, forKey: "customAccentColor")
        }
    }
    @Published var soundEffectsEnabled: Bool = true {
        didSet {
            UserDefaults.standard.set(soundEffectsEnabled, forKey: "soundEffectsEnabled")
        }
    }

    private weak var server: DesktopServer?
    private weak var ollama: OllamaManager?
    let apiClient = NativeAPIClient()
    private var activeSendTask: Task<Void, Never>?
    private var activeAgentJobID: String?
    private var approvedPlanPrompt: String?
    private var telemetryTask: Task<Void, Never>?

    func playSound(_ name: String) {
        guard soundEffectsEnabled else { return }
        NSSound(named: name)?.play()
    }

    init() {
        Self.sharedReference = self
        loadProjects()
        loadConversations()
        selectedProjectID = projects.first?.id
        if !conversations.isEmpty {
            selectedConversationID = conversations.first?.id
        }
        self.animatedBackgroundEnabled = UserDefaults.standard.object(forKey: "animatedBackgroundEnabled") as? Bool ?? true
        self.customAccentColor = UserDefaults.standard.string(forKey: "customAccentColor") ?? "blue"
        self.soundEffectsEnabled = UserDefaults.standard.object(forKey: "soundEffectsEnabled") as? Bool ?? true
    }

    func clearAllConversations() {
        conversations.removeAll()
        newConversation()
        saveConversations()
    }

    var selectedConversation: Conversation? {
        guard let id = selectedConversationID else { return nil }
        return conversations.first(where: { $0.id == id })
    }

    var recentConversations: [Conversation] {
        conversations.sorted { $0.updatedAt > $1.updatedAt }
    }

    func filteredConversations(for project: ProjectWorkspace) -> [Conversation] {
        let query = conversationSearchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return recentConversations.filter { conversation in
            guard conversation.projectPath == project.path else { return false }
            guard !query.isEmpty else { return true }
            return conversation.title.lowercased().contains(query)
                || conversation.messages.contains { $0.content.lowercased().contains(query) }
        }
    }

    var selectedProject: ProjectWorkspace? {
        guard let selectedProjectID else { return projects.first }
        return projects.first(where: { $0.id == selectedProjectID }) ?? projects.first
    }

    func attach(server: DesktopServer, ollama: OllamaManager) {
        self.server = server
        self.ollama = ollama
        startTelemetryPolling()
    }

    func newConversation() {
        guard let project = selectedProject ?? chooseProject(createConversationAfterSelection: false) else {
            statusText = "Choose or create a project folder first."
            return
        }
        let conversation = Conversation(
            id: UUID().uuidString,
            title: "New Conversation",
            project: project.name,
            projectPath: project.path,
            messages: [],
            updatedAt: Date()
        )
        conversations.insert(conversation, at: 0)
        selectedConversationID = conversation.id
        selectedSection = .chat
        saveConversations()
    }

    @discardableResult
    func chooseProject(createConversationAfterSelection: Bool = false) -> ProjectWorkspace? {
        let alert = NSAlert()
        alert.messageText = "Choose a Project Folder"
        alert.informativeText = "Use an existing folder or create a new one. Geocentric agents will work in that directory."
        alert.addButton(withTitle: "Existing Folder")
        alert.addButton(withTitle: "New Folder")
        alert.addButton(withTitle: "Cancel")
        let response = alert.runModal()

        let selectedURL: URL?
        if response == .alertFirstButtonReturn {
            let panel = NSOpenPanel()
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.allowsMultipleSelection = false
            panel.canCreateDirectories = true
            panel.prompt = "Use Folder"
            selectedURL = panel.runModal() == .OK ? panel.url : nil
        } else if response == .alertSecondButtonReturn {
            let panel = NSSavePanel()
            panel.canCreateDirectories = true
            panel.prompt = "Create Project"
            panel.nameFieldStringValue = "New Geocentric Project"
            selectedURL = panel.runModal() == .OK ? panel.url : nil
        } else {
            selectedURL = nil
        }

        guard let url = selectedURL else { return nil }
        do {
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
            let project = upsertProject(url: url)
            if createConversationAfterSelection {
                newConversation()
            }
            return project
        } catch {
            statusText = "Could not use project folder: \(error.localizedDescription)"
            return nil
        }
    }

    func selectProject(_ id: String) {
        selectedProjectID = id
        if let project = selectedProject {
            if let conversation = recentConversations.first(where: { $0.projectPath == project.path }) {
                selectedConversationID = conversation.id
            }
            selectedSection = .chat
        }
    }

    func selectConversation(_ id: String) {
        selectedConversationID = id
        if let conv = conversations.first(where: { $0.id == id }),
           let proj = projects.first(where: { $0.path == conv.projectPath }) {
            selectedProjectID = proj.id
        }
        selectedSection = .chat
    }

    func selectAdjacentConversation(offset: Int) {
        let ordered = recentConversations
        guard let currentID = selectedConversationID,
              let current = ordered.firstIndex(where: { $0.id == currentID })
        else {
            selectedConversationID = ordered.first?.id
            selectedSection = .chat
            return
        }
        let nextIndex = current + offset
        guard ordered.indices.contains(nextIndex) else { return }
        selectedConversationID = ordered[nextIndex].id
        selectedSection = .chat
    }

    func sendPrompt() {
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        guard let ollama else { return }
        guard let project = selectedProject ?? chooseProject(createConversationAfterSelection: false) else {
            statusText = "Choose or create a project folder first."
            return
        }

        let fallback = fallbackAPI
        let canUseOllama = !ollama.selectedModel.isEmpty && ollama.hasSelectedInstalledModel
        if !canUseOllama && !fallback.isConfigured {
            showModels = true
            statusText = "Download an Ollama model or configure a fallback API key first."
            return
        }

        let attachments = pendingAttachments
        let intent = IntentClassifier.classify(text)
        let explicitWorkspaceRequest = promptNeedsWorkspaceTools(text, attachments: attachments)
        let explicitWebRequest = promptNeedsWebTools(text)
        if explicitWorkspaceRequest && approvedPlanPrompt != text {
            createImplementationPlan(for: text, project: project, attachments: attachments)
            return
        }
        approvedPlanPrompt = nil

        let messageContent = text + attachmentPromptSuffix(for: attachments)
        let wantsAgent = canUseOllama && agentMode && (intent != .casual || explicitWorkspaceRequest || explicitWebRequest)
        let useWeb = wantsAgent && (webSearch || explicitWebRequest || intent == .web)
        let requiresAgent = explicitWorkspaceRequest || explicitWebRequest

        prompt = ""
        pendingAttachments.removeAll()
        isSending = true
        activeAgentJobID = nil
        activeAgentProgress = ""
        activeAgentRoadmap = ""
        activeAgentChanges = []
        activeAgentDiffs = []
        if !canUseOllama {
            statusText = "Using fallback API..."
        } else if wantsAgent {
            if server?.isReady == true {
                statusText = useWeb ? "Queueing agent run with web context..." : "Queueing agent run..."
            } else {
                statusText = "Starting local agent service for tools..."
                activeAgentProgress = "Starting local agent service for tools..."
            }
        } else if intent == .casual && agentMode {
            statusText = "Simple message routed to local chat."
        } else {
            statusText = "Chatting with Ollama..."
        }

        if selectedConversationID == nil {
            newConversation()
        }
        guard let convIndex = conversations.firstIndex(where: { $0.id == selectedConversationID }) else {
            isSending = false
            return
        }

        if conversations[convIndex].projectPath == nil {
            conversations[convIndex].project = project.name
            conversations[convIndex].projectPath = project.path
        }

        conversations[convIndex].messages.append(ConversationMessage(role: .user, content: userVisibleContent(text, attachments: attachments)))
        conversations[convIndex].messages.append(ConversationMessage(role: .assistant, content: "Preparing..."))
        conversations[convIndex].updatedAt = Date()
        if conversations[convIndex].title == "New Conversation" {
            conversations[convIndex].title = titleFromPrompt(text)
        }
        let assistantID = conversations[convIndex].messages.last!.id
        var requestConversation = conversations[convIndex]
        if let lastUserIndex = requestConversation.messages.lastIndex(where: { $0.role == .user }) {
            requestConversation.messages[lastUserIndex].content = messageContent
        }
        saveConversations()

        activeSendTask = Task {
            do {
                let response: String
                if wantsAgent, let server {
                    let baseURL: URL
                    if let localURL = server.localURL {
                        baseURL = localURL
                    } else if let readyURL = await server.waitUntilReady(timeout: 120, startIfNeeded: true) {
                        baseURL = readyURL
                    } else if requiresAgent {
                        throw appError("The local agent service could not start, so tools are unavailable. Open the Agent status panel for details, then try again.")
                    } else {
                        response = try await self.streamOllamaResponse(
                            model: ollama.selectedModel,
                            conversation: requestConversation,
                            assistantID: assistantID
                        )
                        DispatchQueue.main.async {
                            self.replaceAssistantMessage(assistantID, with: response)
                            self.isSending = false
                            self.activeSendTask = nil
                            self.activeAgentJobID = nil
                            self.statusText = "Ready"
                            self.saveConversations()
                            self.playSound("Glass")
                        }
                        return
                    }

                    response = try await apiClient.runAgentJob(
                        baseURL: baseURL,
                        model: ollama.selectedModel,
                        conversation: requestConversation,
                        attachments: attachments,
                        searchWeb: useWeb,
                        jobStarted: { [weak self] jobID in
                            DispatchQueue.main.async {
                                self?.activeAgentJobID = jobID
                                self?.lastAgentJobID = jobID
                            }
                        },
                        update: { [weak self] job in
                            DispatchQueue.main.async {
                                self?.statusText = job.progress
                                self?.activeAgentProgress = job.progress
                                self?.activeAgentRoadmap = job.roadmap ?? ""
                                self?.activeAgentChanges = job.changes ?? []
                                self?.activeAgentDiffs = job.diffs ?? []
                                if !job.reply.isEmpty {
                                    self?.replaceAssistantMessage(assistantID, with: job.reply)
                                }
                            }
                        }
                    )
                } else if canUseOllama {
                    response = try await self.streamOllamaResponse(
                        model: ollama.selectedModel,
                        conversation: requestConversation,
                        assistantID: assistantID
                    )
                } else {
                    response = try await apiClient.chatWithFallbackAPI(
                        config: fallback,
                        messages: requestConversation.messages.filter { $0.id != assistantID }
                    )
                }

                DispatchQueue.main.async {
                    self.replaceAssistantMessage(assistantID, with: response)
                    self.isSending = false
                    self.activeSendTask = nil
                    self.activeAgentJobID = nil
                    self.statusText = "Ready"
                    self.saveConversations()
                    self.playSound("Glass")
                }
            } catch {
                let nsError = error as NSError
                let cancelled = error is CancellationError || (nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled)
                DispatchQueue.main.async {
                    self.replaceAssistantMessage(assistantID, with: cancelled ? "Stopped." : "Error: \(error.localizedDescription)")
                    self.isSending = false
                    self.activeSendTask = nil
                    self.activeAgentJobID = nil
                    self.statusText = cancelled ? "Stopped." : error.localizedDescription
                    self.saveConversations()
                    if cancelled {
                        self.playSound("Tink")
                    } else {
                        self.playSound("Basso")
                    }
                }
            }
        }
    }

    private func streamOllamaResponse(model: String, conversation: Conversation, assistantID: UUID) async throws -> String {
        var streamed = ""
        var lastUIUpdate = Date.distantPast
        return try await apiClient.streamChatWithOllama(
            model: model,
            messages: conversation.messages.filter { $0.id != assistantID },
            onStatus: { [weak self] status in
                DispatchQueue.main.async {
                    self?.statusText = status
                }
            },
            onDelta: { [weak self] delta in
                streamed += delta
                let now = Date()
                guard now.timeIntervalSince(lastUIUpdate) > 0.05 || delta.contains("\n") else { return }
                lastUIUpdate = now
                let snapshot = streamed
                DispatchQueue.main.async {
                    self?.replaceAssistantMessage(assistantID, with: snapshot.isEmpty ? "Thinking..." : snapshot)
                }
            }
        )
    }

    func stopResponse() {
        guard isSending else { return }
        statusText = "Stopping response..."
        activeSendTask?.cancel()
        if let jobID = activeAgentJobID, let baseURL = server?.localURL {
            Task {
                try? await apiClient.cancelAgentJob(baseURL: baseURL, jobID: jobID)
            }
        }
        isSending = false
        activeSendTask = nil
        activeAgentJobID = nil
    }

    func chooseAttachments() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.prompt = "Attach"
        let result = panel.runModal()
        guard result == .OK else { return }

        attachFiles(urls: panel.urls)
    }

    func attachFiles(urls: [URL]) {
        var loaded: [LocalAttachment] = []
        for url in urls {
            let scoped = url.startAccessingSecurityScopedResource()
            defer {
                if scoped {
                    url.stopAccessingSecurityScopedResource()
                }
            }

            do {
                let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
                let size = (attributes[.size] as? NSNumber)?.intValue ?? 0
                if size > 75 * 1024 * 1024 {
                    statusText = "\(url.lastPathComponent) is larger than 75 MB."
                    continue
                }
                let data = try Data(contentsOf: url)
                let mime = mimeType(for: url)
                let dataURL = "data:\(mime);base64,\(data.base64EncodedString())"
                loaded.append(LocalAttachment(
                    name: url.lastPathComponent,
                    url: url,
                    mime: mime,
                    byteCount: data.count,
                    dataURL: dataURL,
                    textExcerpt: textExcerpt(from: data, mime: mime)
                ))
            } catch {
                statusText = "Could not attach \(url.lastPathComponent): \(error.localizedDescription)"
            }
        }

        pendingAttachments.append(contentsOf: loaded)
        if !loaded.isEmpty {
            statusText = "Attached \(loaded.count) file\(loaded.count == 1 ? "" : "s")."
        }
    }

    func removeAttachment(_ attachment: LocalAttachment) {
        pendingAttachments.removeAll { $0.id == attachment.id }
    }

    func chooseStagedContextFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.prompt = "Pin"
        let result = panel.runModal()
        guard result == .OK else { return }

        for url in panel.urls {
            let scoped = url.startAccessingSecurityScopedResource()
            defer {
                if scoped {
                    url.stopAccessingSecurityScopedResource()
                }
            }

            do {
                let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
                let size = (attributes[.size] as? NSNumber)?.intValue ?? 0
                let excerpt = textExcerpt(fromFileAt: url, mime: mimeType(for: url)) ?? ""
                let staged = StagedContextFile(
                    name: url.lastPathComponent,
                    path: url.path,
                    byteCount: size,
                    excerpt: String(excerpt.prefix(8_000))
                )
                if !stagedContextFiles.contains(where: { $0.path == staged.path }) {
                    stagedContextFiles.append(staged)
                }
            } catch {
                statusText = "Could not pin \(url.lastPathComponent): \(error.localizedDescription)"
            }
        }
    }

    func removeStagedContextFile(_ file: StagedContextFile) {
        stagedContextFiles.removeAll { $0.id == file.id }
    }

    func acceptImplementationPlan() {
        guard let plan = pendingImplementationPlan else { return }
        approvedPlanPrompt = plan.prompt
        pendingImplementationPlan = nil
        prompt = plan.prompt
        sendPrompt()
    }

    func denyImplementationPlan() {
        pendingImplementationPlan = nil
        statusText = "Implementation plan cancelled."
    }

    func compactContext() {
        guard let convID = selectedConversationID,
              let index = conversations.firstIndex(where: { $0.id == convID })
        else { return }
        let messages = conversations[index].messages
        guard messages.count > 6 else {
            statusText = "Context is already compact."
            return
        }
        let older = messages.dropLast(6)
        let summary = older
            .suffix(10)
            .map { "\($0.role.rawValue): \(String($0.content.prefix(220)))" }
            .joined(separator: "\n")
        let compacted = ConversationMessage(role: .system, content: "Compacted context summary:\n\(summary)")
        conversations[index].messages = [compacted] + Array(messages.suffix(6))
        conversations[index].updatedAt = Date()
        saveConversations()
        statusText = "Compacted older context."
    }

    func rollbackDiff(_ diff: WorkspaceDiff) {
        guard let jobID = activeAgentJobID ?? lastAgentJobID, let baseURL = server?.localURL else { return }
        Task {
            do {
                try await apiClient.rollbackDiff(baseURL: baseURL, jobID: jobID, path: diff.path)
                DispatchQueue.main.async {
                    self.statusText = "Rolled back \(diff.path)"
                    self.activeAgentDiffs.removeAll { $0.path == diff.path }
                    self.activeAgentChanges.removeAll { $0.path == diff.path }
                }
            } catch {
                DispatchQueue.main.async {
                    self.statusText = "Rollback failed: \(error.localizedDescription)"
                }
            }
        }
    }

    func approveDiff(_ diff: WorkspaceDiff) {
        guard let jobID = activeAgentJobID ?? lastAgentJobID, let baseURL = server?.localURL else {
            activeAgentDiffs.removeAll { $0.path == diff.path }
            return
        }
        Task {
            do {
                try await apiClient.approveDiff(baseURL: baseURL, jobID: jobID, path: diff.path)
                DispatchQueue.main.async {
                    self.statusText = "Approved \(diff.path)"
                    self.activeAgentDiffs.removeAll { $0.path == diff.path }
                }
            } catch {
                DispatchQueue.main.async {
                    self.statusText = "Approve failed: \(error.localizedDescription)"
                }
            }
        }
    }

    func saveFallbackAPI(baseURL: String, apiKey: String, model: String) {
        fallbackAPI = FallbackAPIConfig(baseURL: baseURL, apiKey: apiKey, model: model)
        fallbackAPI.save()
        statusText = fallbackAPI.isConfigured ? "Fallback API configured." : "Fallback API cleared."
    }

    func deleteConversation(_ id: String) {
        conversations.removeAll { $0.id == id }
        if selectedConversationID == id {
            selectedConversationID = recentConversations.first?.id
        }
        if conversations.isEmpty {
            newConversation()
        } else {
            saveConversations()
        }
    }

    func removeProject(_ id: String) {
        projects.removeAll { $0.id == id }
        if selectedProjectID == id {
            selectedProjectID = projects.first?.id
        }
        saveProjects()
    }

    func retryLastUserMessage() {
        guard !isSending,
              let convID = selectedConversationID,
              let convIndex = conversations.firstIndex(where: { $0.id == convID }),
              let lastUserIndex = conversations[convIndex].messages.lastIndex(where: { $0.role == .user })
        else { return }

        let content = conversations[convIndex].messages[lastUserIndex].content
        let visiblePrompt = content.components(separatedBy: "\n\nAttached:").first ?? content
        conversations[convIndex].messages.removeSubrange(lastUserIndex..<conversations[convIndex].messages.endIndex)
        conversations[convIndex].updatedAt = Date()
        prompt = visiblePrompt
        saveConversations()
        sendPrompt()
    }

    func exportConversation(_ conversation: Conversation? = nil) {
        guard let conversation = conversation ?? selectedConversation else {
            statusText = "No conversation selected."
            return
        }

        let panel = NSSavePanel()
        panel.canCreateDirectories = true
        panel.nameFieldStringValue = "\(safeFilename(conversation.title)).md"
        panel.prompt = "Export"
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            do {
                try self?.conversationMarkdown(conversation).write(to: url, atomically: true, encoding: .utf8)
                DispatchQueue.main.async {
                    self?.statusText = "Exported \(conversation.title)."
                    self?.playSound("Glass")
                }
            } catch {
                DispatchQueue.main.async {
                    self?.statusText = "Export failed: \(error.localizedDescription)"
                    self?.playSound("Basso")
                }
            }
        }
    }

    private func replaceAssistantMessage(_ id: UUID, with content: String) {
        guard let convIndex = conversations.firstIndex(where: { $0.id == selectedConversationID }),
              let msgIndex = conversations[convIndex].messages.firstIndex(where: { $0.id == id })
        else { return }
        conversations[convIndex].messages[msgIndex].content = content
        conversations[convIndex].updatedAt = Date()
    }

    private func titleFromPrompt(_ prompt: String) -> String {
        let words = prompt.split(separator: " ").prefix(6).joined(separator: " ")
        return words.isEmpty ? "New Conversation" : words
    }

    private func promptNeedsWorkspaceTools(_ text: String, attachments: [LocalAttachment]) -> Bool {
        if !attachments.isEmpty { return true }
        let lowered = text.lowercased()
        let actionPattern = #"\b(make|create|write|edit|update|fix|debug|delete|remove|rename|move|run|execute|install|build|scaffold|save)\b"#
        let artifactPattern = #"\b(file|files|folder|directory|script|app|application|website|web app|project|page|component|server|api|terminal|command|doc|document|email|mail)\b|\.(txt|md|markdown|py|js|jsx|ts|tsx|html|css|json|csv|sh|yaml|yml|toml|sql)\b"#
        let strongPattern = #"\b(on my computer|in the workspace|inside the workspace|downloadable|download link|run this|test this|terminal command|shell command)\b"#

        return matches(lowered, strongPattern) || (matches(lowered, actionPattern) && matches(lowered, artifactPattern))
    }

    private func promptNeedsWebTools(_ text: String) -> Bool {
        let lowered = text.lowercased()
        let searchPattern = #"\b(search|web search|look up|lookup|google|browse|internet|online|news|latest|newest|current|today|recent|upcoming|real[- ]?time|who is the current|what is the current)\b"#
        return matches(lowered, searchPattern)
    }

    private func matches(_ text: String, _ pattern: String) -> Bool {
        text.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
    }

    private func appError(_ message: String) -> NSError {
        NSError(domain: "GeocentricNativeApp", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private func upsertProject(url: URL) -> ProjectWorkspace {
        let standardized = url.standardizedFileURL
        let path = standardized.path
        if let index = projects.firstIndex(where: { $0.path == path }) {
            projects[index].updatedAt = Date()
            selectedProjectID = projects[index].id
            saveProjects()
            return projects[index]
        }

        let project = ProjectWorkspace(
            id: UUID().uuidString,
            name: standardized.lastPathComponent.isEmpty ? path : standardized.lastPathComponent,
            path: path,
            createdAt: Date(),
            updatedAt: Date()
        )
        projects.insert(project, at: 0)
        selectedProjectID = project.id
        saveProjects()
        return project
    }

    private func loadProjects() {
        guard let data = try? Data(contentsOf: projectsURL()) else { return }
        if let decoded = try? JSONDecoder().decode([ProjectWorkspace].self, from: data) {
            projects = decoded
                .filter { FileManager.default.fileExists(atPath: $0.path) }
                .sorted { $0.updatedAt > $1.updatedAt }
        }
    }

    func saveProjects() {
        do {
            let url = projectsURL()
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONEncoder().encode(projects)
            try data.write(to: url, options: .atomic)
        } catch {
            statusText = "Could not save projects: \(error.localizedDescription)"
        }
    }

    private func userVisibleContent(_ text: String, attachments: [LocalAttachment]) -> String {
        guard !attachments.isEmpty else { return text }
        let names = attachments.map { $0.name }.joined(separator: ", ")
        return text + "\n\nAttached: \(names)"
    }

    private func attachmentPromptSuffix(for attachments: [LocalAttachment]) -> String {
        guard !attachments.isEmpty || !stagedContextFiles.isEmpty else { return "" }
        var lines = ["\n\n[Attached files]"]
        for attachment in attachments {
            lines.append("- \(attachment.name) (\(attachment.mime), \(ByteCountFormatter.string(fromByteCount: Int64(attachment.byteCount), countStyle: .file)))")
            if let excerpt = attachment.textExcerpt, !excerpt.isEmpty {
                lines.append("Excerpt from \(attachment.name):\n\(excerpt)")
            }
        }
        if !stagedContextFiles.isEmpty {
            lines.append("\n[Staged context files]")
            for file in stagedContextFiles {
                lines.append("- \(file.path) (\(ByteCountFormatter.string(fromByteCount: Int64(file.byteCount), countStyle: .file)))")
                if !file.excerpt.isEmpty {
                    lines.append("Excerpt from \(file.name):\n\(file.excerpt)")
                }
            }
        }
        return lines.joined(separator: "\n")
    }

    private func createImplementationPlan(for text: String, project: ProjectWorkspace, attachments: [LocalAttachment]) {
        let staged = stagedContextFiles.map { "- \($0.path)" }.joined(separator: "\n")
        let attached = attachments.map { "- \($0.name)" }.joined(separator: "\n")
        let markdown = """
        # Implementation Plan

        ## Objective
        \(text)

        ## Proposed Steps
        - Confirm the requested scope and work only inside the selected project/workspace.
        - Inspect any pinned or attached files needed for the change.
        - Apply the smallest set of file edits needed to satisfy the request.
        - Run a focused verification command or app check.
        - Show changed files with a diff and keep rollback available until approved.

        ## Context
        Project: \(project.path)
        \(staged.isEmpty ? "Pinned files: none" : "Pinned files:\n\(staged)")
        \(attached.isEmpty ? "Attachments: none" : "Attachments:\n\(attached)")

        ## Review
        Press Accept to allow the agent to execute this plan, or Deny to cancel before any agent tool run starts.
        """

        pendingImplementationPlan = ImplementationPlan(prompt: text, markdown: markdown)
        statusText = "Review the implementation plan before the agent runs."

        let planURL = URL(fileURLWithPath: project.path).appendingPathComponent("Implementation Plan.md")
        try? markdown.write(to: planURL, atomically: true, encoding: .utf8)
    }

    private func startTelemetryPolling() {
        guard telemetryTask == nil else { return }
        telemetryTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                if let baseURL = self.server?.localURL {
                    do {
                        let snapshot = try await self.apiClient.fetchTelemetry(baseURL: baseURL)
                        DispatchQueue.main.async {
                            self.telemetry = snapshot
                        }
                    } catch {
                        await MainActor.run {
                            self.updateFallbackTelemetry()
                        }
                    }
                } else {
                    await MainActor.run {
                        self.updateFallbackTelemetry()
                    }
                }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    private func updateFallbackTelemetry() {
        var loads = [Double](repeating: 0, count: 3)
        let count = getloadavg(&loads, 3)
        let cpuCount = max(1, ProcessInfo.processInfo.processorCount)
        let cpu = count > 0 ? min(100, max(0, (loads[0] / Double(cpuCount)) * 100)) : 0
        telemetry = SystemTelemetry(
            cpuPercent: cpu,
            memoryPercent: localMemoryUsagePercent() ?? telemetry.memoryPercent,
            diskPercent: localDiskUsagePercent() ?? telemetry.diskPercent,
            gpuPercent: nil
        )
    }

    var contextUsageRatio: Double {
        let conversationText = selectedConversation?.messages.map(\.content).joined(separator: "\n") ?? ""
        let stagedText = stagedContextFiles.map(\.excerpt).joined(separator: "\n")
        let chars = conversationText.count + prompt.count + stagedText.count
        let estimatedTokens = max(1, chars / 4)
        return min(1, Double(estimatedTokens) / 8_000.0)
    }

    private func mimeType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "txt", "md", "markdown", "log": return "text/plain"
        case "json": return "application/json"
        case "csv": return "text/csv"
        case "html", "htm": return "text/html"
        case "css": return "text/css"
        case "js", "mjs", "ts", "tsx", "jsx": return "text/javascript"
        case "swift": return "text/x-swift"
        case "py": return "text/x-python"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "gif": return "image/gif"
        case "webp": return "image/webp"
        case "pdf": return "application/pdf"
        case "zip": return "application/zip"
        default: return "application/octet-stream"
        }
    }

    private func textExcerpt(from data: Data, mime: String) -> String? {
        guard mime.hasPrefix("text/") || ["application/json"].contains(mime) else { return nil }
        guard let text = String(data: data.prefix(64 * 1024), encoding: .utf8) else { return nil }
        return String(text.prefix(12_000))
    }

    private func textExcerpt(fromFileAt url: URL, mime: String, maxBytes: Int = 256 * 1024) -> String? {
        guard mime.hasPrefix("text/") || ["application/json"].contains(mime) else { return nil }
        guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? handle.close() }
        let data = handle.readData(ofLength: maxBytes)
        guard let text = String(data: data, encoding: .utf8) else { return nil }
        return String(text.prefix(12_000))
    }

    private func localDiskUsagePercent() -> Double? {
        guard let attrs = try? FileManager.default.attributesOfFileSystem(forPath: NSHomeDirectory()),
              let size = attrs[.systemSize] as? NSNumber,
              let free = attrs[.systemFreeSize] as? NSNumber,
              size.doubleValue > 0
        else { return nil }

        return min(100, max(0, ((size.doubleValue - free.doubleValue) / size.doubleValue) * 100))
    }

    private func localMemoryUsagePercent() -> Double? {
        var stats = vm_statistics64()
        var count = mach_msg_type_number_t(MemoryLayout<vm_statistics64_data_t>.stride / MemoryLayout<integer_t>.stride)
        let result = withUnsafeMutablePointer(to: &stats) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return nil }

        let usedPages = UInt64(stats.active_count + stats.inactive_count + stats.wire_count + stats.compressor_page_count)
        let usedBytes = Double(usedPages) * Double(vm_kernel_page_size)
        let totalBytes = Double(ProcessInfo.processInfo.physicalMemory)
        guard totalBytes > 0 else { return nil }
        return min(100, max(0, (usedBytes / totalBytes) * 100))
    }

    private func conversationMarkdown(_ conversation: Conversation) -> String {
        let formatter = ISO8601DateFormatter()
        var lines: [String] = [
            "# \(conversation.title)",
            "",
            "- Project: \(conversation.project)",
            "- Updated: \(formatter.string(from: conversation.updatedAt))",
            ""
        ]

        for message in conversation.messages {
            lines.append("## \(message.role.rawValue.capitalized)")
            lines.append("")
            lines.append(message.content)
            lines.append("")
        }

        return lines.joined(separator: "\n")
    }

    private func safeFilename(_ text: String) -> String {
        let invalid = CharacterSet(charactersIn: "/\\?%*|\"<>:")
        let cleaned = text
            .components(separatedBy: invalid)
            .joined(separator: "-")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? "Geocentric Conversation" : String(cleaned.prefix(80))
    }

    private func loadConversations() {
        guard let data = try? Data(contentsOf: conversationsURL()) else { return }
        if let decoded = try? JSONDecoder().decode([Conversation].self, from: data) {
            conversations = decoded.sorted { $0.updatedAt > $1.updatedAt }
        }
    }

    func saveConversations() {
        do {
            let url = conversationsURL()
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONEncoder().encode(conversations)
            try data.write(to: url, options: .atomic)
        } catch {
            statusText = "Could not save conversations: \(error.localizedDescription)"
        }
    }

    private func conversationsURL() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Geocentric", isDirectory: true)
            .appendingPathComponent("NativeConversations.json")
    }

    private func projectsURL() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("Geocentric", isDirectory: true)
            .appendingPathComponent("Projects.json")
    }
}
