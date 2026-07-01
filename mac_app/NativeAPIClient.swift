import Foundation

private let ollamaAPIBase = URL(string: "http://127.0.0.1:11434")!

struct OllamaChatResponse: Decodable {
    struct Message: Decodable {
        var role: String
        var content: String
    }
    var message: Message
}

struct OllamaStreamChunk: Decodable {
    struct Message: Decodable {
        var role: String?
        var content: String
    }
    var message: Message?
    var done: Bool?
    var done_reason: String?
}

struct FallbackChatResponse: Decodable {
    struct Choice: Decodable {
        struct Message: Decodable {
            var role: String?
            var content: String
        }
        var message: Message
    }
    var choices: [Choice]
}

struct AuthResponse: Decodable {
    var token: String
}

struct NativeHTTPError: LocalizedError {
    var statusCode: Int
    var message: String

    var errorDescription: String? {
        message
    }
}

struct AgentJobStartResponse: Decodable {
    var jobId: String
    var chatId: String
    var status: String
    var progress: String
    var roadmap: String?
}

struct AgentJobEnvelope: Decodable {
    var job: AgentJob
}

struct AgentJob: Decodable {
    var id: String
    var status: String
    var progress: String
    var roadmap: String?
    var changes: [WorkspaceChange]?
    var diffs: [WorkspaceDiff]?
    var reply: String
    var error: String
}

struct TelemetryResponse: Decodable {
    var cpuPercent: Double
    var memoryPercent: Double
    var diskPercent: Double
    var gpuPercent: Double?
}

struct CronJobsResponse: Decodable {
    var jobs: [ScheduledTask]
}

struct ScheduledTask: Identifiable, Decodable, Equatable {
    var id: String
    var name: String
    var prompt: String
    var model: String?
    var interval_hours: Int
    var interval_minutes: Int
    var last_run: Double?
    var created_at: Double?
}

final class NativeAPIClient {
    private let tokenKey = "nativeAPIToken"
    private let emailKey = "nativeAPIEmail"
    private let passwordKey = "nativeAPIPassword"

    func runAgentJob(
        baseURL: URL,
        model: String,
        conversation: Conversation,
        attachments: [LocalAttachment],
        searchWeb: Bool,
        jobStarted: @escaping (String) -> Void,
        update: @escaping (AgentJob) -> Void
    ) async throws -> String {
        var token = try await ensureSession(baseURL: baseURL)
        let outboundMessages = conversation.messages.filter { !($0.role == .assistant && $0.content == "Preparing...") }
        let attachmentPayloads = attachments.map {
            [
                "name": $0.name,
                "type": $0.mime,
                "dataUrl": $0.dataURL
            ]
        }
        let startBody: [String: Any] = [
            "model": model,
            "conversationId": conversation.id,
            "messages": outboundMessages.map { ["role": $0.role.rawValue, "content": $0.content] },
            "attachments": attachmentPayloads,
            "projectPath": conversation.projectPath ?? "",
            "stream": true,
            "agentMode": true,
            "modelMode": "thinking",
            "searchWeb": searchWeb
        ]
        let start: Data
        do {
            start = try await postJSON(
                baseURL.appendingPathComponent("api/chat/jobs"),
                token: token,
                body: startBody
            )
        } catch {
            guard isAuthorizationFailure(error) else { throw error }
            clearSession()
            token = try await ensureSession(baseURL: baseURL)
            start = try await postJSON(
                baseURL.appendingPathComponent("api/chat/jobs"),
                token: token,
                body: startBody
            )
        }
        let startResponse = try JSONDecoder().decode(AgentJobStartResponse.self, from: start)
        jobStarted(startResponse.jobId)
        update(AgentJob(
            id: startResponse.jobId,
            status: startResponse.status,
            progress: startResponse.progress,
            roadmap: startResponse.roadmap,
            changes: [],
            diffs: [],
            reply: "",
            error: ""
        ))

        let deadline = Date().addingTimeInterval(60 * 60)
        while Date() < deadline {
            try Task.checkCancellation()
            try await Task.sleep(nanoseconds: 1_000_000_000)
            let data: Data
            do {
                data = try await getJSON(
                    baseURL.appendingPathComponent("api/chat/jobs/\(startResponse.jobId)"),
                    token: token
                )
            } catch {
                guard isAuthorizationFailure(error) else { throw error }
                clearSession()
                token = try await ensureSession(baseURL: baseURL)
                continue
            }
            let envelope = try JSONDecoder().decode(AgentJobEnvelope.self, from: data)
            let job = envelope.job
            update(job)
            if job.status == "completed" {
                return job.reply.isEmpty ? "Done." : job.reply
            }
            if job.status == "cancelled" {
                throw CancellationError()
            }
            if job.status == "failed" {
                throw appError(job.error.isEmpty ? "Agent job failed." : job.error)
            }
        }
        throw appError("Agent job timed out.")
    }

    func cancelAgentJob(baseURL: URL, jobID: String) async throws {
        _ = try await withSessionRetry(baseURL: baseURL) { token in
            try await self.postJSON(
                baseURL.appendingPathComponent("api/chat/jobs/\(jobID)/cancel"),
                token: token,
                body: [:]
            )
        }
    }

    func streamChatWithOllama(
        model: String,
        messages: [ConversationMessage],
        onStatus: @escaping (String) -> Void,
        onDelta: @escaping (String) -> Void
    ) async throws -> String {
        var fullText = ""
        var workingMessages = messages

        let maxContinuationTurns = 3
        for turn in 0..<maxContinuationTurns {
            try Task.checkCancellation()
            let priorText = fullText
            let url = ollamaAPIBase.appendingPathComponent("api/chat")
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.timeoutInterval = 3600
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: [
                "model": model,
                "stream": true,
                "messages": workingMessages.map { ["role": $0.role.rawValue, "content": $0.content] }
            ])

            let (bytes, response) = try await URLSession.shared.bytes(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw appError("Ollama chat request failed.")
            }

            var turnText = ""
            var doneReason = ""
            for try await line in bytes.lines {
                try Task.checkCancellation()
                guard !line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { continue }
                guard let data = line.data(using: .utf8) else { continue }
                let chunk = try JSONDecoder().decode(OllamaStreamChunk.self, from: data)
                if let content = chunk.message?.content, !content.isEmpty {
                    fullText += content
                    turnText += content
                    onDelta(content)
                }
                if chunk.done == true {
                    doneReason = chunk.done_reason ?? ""
                    break
                }
            }

            if turn > 0 && looksLikeRestartedContinuation(previous: priorText, continuation: turnText) {
                fullText = priorText
                break
            }

            if shouldContinueAfterTokenLimit(doneReason: doneReason, text: turnText), turn + 1 < maxContinuationTurns {
                onStatus("Context compacted after the model hit its token limit. Continuing from the cutoff...")
                workingMessages = compactMessagesForContinuation(original: messages, assistantText: fullText)
                continue
            }
            break
        }

        return fullText.isEmpty ? "Done." : fullText
    }

    private func shouldContinueAfterTokenLimit(doneReason: String, text: String) -> Bool {
        if doneReason.lowercased().contains("length") {
            return true
        }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.filter({ $0 == "`" }).count % 3 != 0 {
            return true
        }
        return trimmed.hasSuffix("<write_file") || trimmed.hasSuffix("<run_command") || trimmed.hasSuffix("<status")
    }

    private func looksLikeRestartedContinuation(previous: String, continuation: String) -> Bool {
        let old = normalizedForOverlap(previous)
        let new = normalizedForOverlap(continuation)
        guard old.count > 80, new.count > 80 else { return false }

        let sample = String(new.prefix(min(160, new.count)))
        if old.contains(sample) {
            return true
        }

        let oldWords = old.split(separator: " ").prefix(80)
        let newWords = new.split(separator: " ").prefix(80)
        guard oldWords.count >= 20, newWords.count >= 20 else { return false }
        let shared = Set(oldWords).intersection(Set(newWords)).count
        return Double(shared) / Double(newWords.count) > 0.72
    }

    private func normalizedForOverlap(_ text: String) -> String {
        text
            .lowercased()
            .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func compactMessagesForContinuation(original: [ConversationMessage], assistantText: String) -> [ConversationMessage] {
        var messages = original
        messages.append(ConversationMessage(role: .assistant, content: assistantText))
        messages.append(ConversationMessage(role: .user, content: "Continue generating your previous response exactly where it was cut off. Do not repeat any part of the previous text. Start immediately with the continuation character."))
        return messages
    }

    func chatWithFallbackAPI(config: FallbackAPIConfig, messages: [ConversationMessage]) async throws -> String {
        guard config.isConfigured else {
            throw appError("Fallback API is not configured.")
        }
        guard let baseURL = URL(string: config.baseURL.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw appError("Fallback API base URL is invalid.")
        }
        let url = baseURL.appendingPathComponent("chat/completions")
        let data = try await postJSON(
            url,
            token: config.apiKey,
            body: [
                "model": config.model,
                "messages": messages.map { ["role": $0.role.rawValue, "content": $0.content] },
                "stream": false
            ],
            authorizationPrefix: "Bearer"
        )
        let response = try JSONDecoder().decode(FallbackChatResponse.self, from: data)
        guard let content = response.choices.first?.message.content, !content.isEmpty else {
            throw appError("Fallback API returned an empty response.")
        }
        return content
    }

    func listCronJobs(baseURL: URL) async throws -> [ScheduledTask] {
        let data = try await withSessionRetry(baseURL: baseURL) { token in
            try await self.getJSON(baseURL.appendingPathComponent("api/cron-jobs"), token: token)
        }
        return try JSONDecoder().decode(CronJobsResponse.self, from: data).jobs
    }

    func createCronJob(baseURL: URL, name: String, prompt: String, hours: Int, minutes: Int, model: String) async throws {
        _ = try await withSessionRetry(baseURL: baseURL) { token in
            try await self.postJSON(
                baseURL.appendingPathComponent("api/cron-jobs"),
                token: token,
                body: [
                    "name": name,
                    "prompt": prompt,
                    "interval_hours": hours,
                    "interval_minutes": minutes,
                    "model": model
                ]
            )
        }
    }

    func deleteCronJob(baseURL: URL, id: String) async throws {
        try await withSessionRetry(baseURL: baseURL) { token in
            try await self.deleteJSON(baseURL.appendingPathComponent("api/cron-jobs/\(id)"), token: token)
        }
    }

    func authenticatedGetJSON(baseURL: URL, path: String) async throws -> Data {
        try await withSessionRetry(baseURL: baseURL) { token in
            try await self.getJSON(baseURL.appendingPathComponent(path), token: token)
        }
    }

    func authenticatedPostJSON(baseURL: URL, path: String, body: [String: Any]) async throws -> Data {
        try await withSessionRetry(baseURL: baseURL) { token in
            try await self.postJSON(baseURL.appendingPathComponent(path), token: token, body: body)
        }
    }

    func fetchTelemetry(baseURL: URL) async throws -> SystemTelemetry {
        let data = try await withSessionRetry(baseURL: baseURL) { token in
            try await self.getJSON(baseURL.appendingPathComponent("api/system/telemetry"), token: token)
        }
        let response = try JSONDecoder().decode(TelemetryResponse.self, from: data)
        return SystemTelemetry(
            cpuPercent: response.cpuPercent,
            memoryPercent: response.memoryPercent,
            diskPercent: response.diskPercent,
            gpuPercent: response.gpuPercent
        )
    }

    func rollbackDiff(baseURL: URL, jobID: String, path: String) async throws {
        _ = try await withSessionRetry(baseURL: baseURL) { token in
            try await self.postJSON(
                baseURL.appendingPathComponent("api/chat/jobs/\(jobID)/rollback"),
                token: token,
                body: ["path": path]
            )
        }
    }

    func approveDiff(baseURL: URL, jobID: String, path: String) async throws {
        _ = try await withSessionRetry(baseURL: baseURL) { token in
            try await self.postJSON(
                baseURL.appendingPathComponent("api/chat/jobs/\(jobID)/approve"),
                token: token,
                body: ["path": path]
            )
        }
    }

    func ensureSession(baseURL: URL) async throws -> String {
        if let token = LocalSecrets.string(for: tokenKey, migrateFromDefaults: true), !token.isEmpty {
            return token
        }

        let email: String
        let password: String
        if let existingEmail = LocalSecrets.string(for: emailKey, migrateFromDefaults: true),
           let existingPassword = LocalSecrets.string(for: passwordKey, migrateFromDefaults: true) {
            email = existingEmail
            password = existingPassword
        } else {
            email = "local-\(UUID().uuidString.lowercased())@geocentric.local"
            password = UUID().uuidString + UUID().uuidString
            LocalSecrets.set(email, for: emailKey)
            LocalSecrets.set(password, for: passwordKey)
        }

        do {
            let signupData = try await postJSON(
                baseURL.appendingPathComponent("api/auth/signup"),
                token: nil,
                body: ["name": "Local Workspace", "email": email, "password": password]
            )
            let auth = try JSONDecoder().decode(AuthResponse.self, from: signupData)
            LocalSecrets.set(auth.token, for: tokenKey)
            return auth.token
        } catch {
            let loginData = try await postJSON(
                baseURL.appendingPathComponent("api/auth/login"),
                token: nil,
                body: ["email": email, "password": password]
            )
            let auth = try JSONDecoder().decode(AuthResponse.self, from: loginData)
            LocalSecrets.set(auth.token, for: tokenKey)
            return auth.token
        }
    }

    func clearSession() {
        LocalSecrets.delete(tokenKey)
    }

    func postJSON(_ url: URL, token: String?, body: [String: Any], authorizationPrefix: String = "Bearer") async throws -> Data {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 3600
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token {
            request.setValue("\(authorizationPrefix) \(token)", forHTTPHeaderField: "Authorization")
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw decodeHTTPError(data: data, statusCode: (response as? HTTPURLResponse)?.statusCode ?? -1)
        }
        return data
    }

    func getJSON(_ url: URL, token: String?) async throws -> Data {
        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw decodeHTTPError(data: data, statusCode: (response as? HTTPURLResponse)?.statusCode ?? -1)
        }
        return data
    }

    private func deleteJSON(_ url: URL, token: String?) async throws {
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.timeoutInterval = 30
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw decodeHTTPError(data: data, statusCode: (response as? HTTPURLResponse)?.statusCode ?? -1)
        }
    }

    private func withSessionRetry<T>(baseURL: URL, operation: (String) async throws -> T) async throws -> T {
        let token = try await ensureSession(baseURL: baseURL)
        do {
            return try await operation(token)
        } catch {
            guard isAuthorizationFailure(error) else { throw error }
            clearSession()
            let refreshed = try await ensureSession(baseURL: baseURL)
            return try await operation(refreshed)
        }
    }

    private func isAuthorizationFailure(_ error: Error) -> Bool {
        guard let http = error as? NativeHTTPError else { return false }
        return http.statusCode == 401 || http.statusCode == 403
    }

    private func decodeHTTPError(data: Data, statusCode: Int) -> Error {
        var message: String?
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = json["detail"] {
            message = String(describing: detail)
        } else if let text = String(data: data, encoding: .utf8), !text.isEmpty {
            message = text
        }
        if statusCode > 0 {
            return NativeHTTPError(statusCode: statusCode, message: message ?? "Request failed with HTTP \(statusCode).")
        }
        return appError(message ?? "Request failed.")
    }

    private func appError(_ message: String) -> NSError {
        NSError(domain: "GeocentricNativeAPI", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
