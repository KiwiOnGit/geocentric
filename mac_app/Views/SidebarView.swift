import SwiftUI
import AppKit

struct SidebarView: View {
    @EnvironmentObject private var appModel: NativeAppModel
    @StateObject private var updater = AppUpdater.shared

    var body: some View {
        List {
            Section(header: Text("Geocentric").font(.system(size: 10, weight: .bold)).foregroundStyle(Color.white.opacity(0.6))) {
                SidebarItem(title: "Chat Workspace", icon: "bubble.left.and.bubble.right", active: appModel.selectedSection == .chat) {
                    appModel.selectedSection = .chat
                }
                SidebarItem(title: "History", icon: "clock", active: appModel.selectedSection == .history) {
                    appModel.selectedSection = .history
                }
                SidebarItem(title: "Scheduled Tasks", icon: "timer", active: appModel.selectedSection == .tasks) {
                    appModel.selectedSection = .tasks
                }
            }

            Section {
                HStack(spacing: 7) {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Color.white.opacity(0.58))
                    TextField("Search threads", text: $appModel.conversationSearchText)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                    if !appModel.conversationSearchText.isEmpty {
                        Button {
                            appModel.conversationSearchText = ""
                        } label: {
                            Image(systemName: "xmark.circle.fill")
                                .font(.system(size: 11))
                                .foregroundStyle(Color.white.opacity(0.5))
                        }
                        .buttonStyle(.plain)
                        .help("Clear Search")
                    }
                }
                .padding(.horizontal, 8)
                .frame(height: 28)
                .background(Color.white.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 5))
            }
            
            Section(header: HStack {
                Text("Projects").font(.system(size: 10, weight: .bold)).foregroundStyle(Color.white.opacity(0.6))
                Spacer()
                Button {
                    appModel.chooseProject(createConversationAfterSelection: true)
                } label: {
                    Image(systemName: "folder.badge.plus")
                        .font(.system(size: 11))
                        .foregroundStyle(Color.white.opacity(0.6))
                }
                .buttonStyle(.plain)
                .help("Add or create a project folder")
                .pointerHover()
            }
            .padding(.trailing, 10)) {
                if appModel.projects.isEmpty {
                    SidebarItem(title: "Choose folder...", icon: "folder.badge.plus", active: false) {
                        appModel.chooseProject(createConversationAfterSelection: true)
                    }
                } else {
                    ForEach(appModel.projects) { project in
                        ProjectSidebarGroup(
                            project: project,
                            conversations: appModel.filteredConversations(for: project)
                        )
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .scrollContentBackground(.hidden)
        .background(Color.clear)
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 0) {
                Divider()
                HStack {
                    SidebarItem(title: "Settings", icon: "gearshape", active: appModel.selectedSection == .settings, showBadge: updater.showUpdateBadge) {
                        appModel.selectedSection = .settings
                    }
                }
                .padding(8)
                .background(.ultraThinMaterial)
            }
        }
    }
}

struct SidebarItem: View {
    let title: String
    let icon: String
    let active: Bool
    var showBadge: Bool = false
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 12, weight: active ? .semibold : .regular))
                    .frame(width: 16)
                    .foregroundStyle(active ? Color.white : (hovering ? Color.white : Color.white.opacity(0.65)))
                Text(title)
                    .font(.system(size: 13, weight: active ? .semibold : .regular))
                    .foregroundStyle(active ? Color.white : (hovering ? Color.white : Color.white.opacity(0.88)))
                Spacer()
                if showBadge {
                    Circle()
                        .fill(Color.red)
                        .frame(width: 6, height: 6)
                }
            }
            .contentShape(Rectangle())
            .padding(.horizontal, 8)
            .frame(height: 28)
            .background(
                ZStack {
                    if active {
                        Color.geocentricAccent
                    } else if hovering {
                        Color.white.opacity(0.08)
                    }
                }
            )
            .clipShape(RoundedRectangle(cornerRadius: 5))
            .onHover { hovering = $0 }
        }
        .buttonStyle(.plain)
        .pointerHover()
    }
}

struct ProjectSidebarGroup: View {
    @EnvironmentObject private var appModel: NativeAppModel
    let project: ProjectWorkspace
    let conversations: [Conversation]
    @State private var expanded = true

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) {
                    expanded.toggle()
                }
            } label: {
                let isSelected = appModel.selectedProjectID == project.id
                HStack(spacing: 6) {
                    Image(systemName: expanded ? "folder.fill" : "folder")
                        .foregroundStyle(isSelected ? Color.white : Color.white.opacity(0.65))
                    Text(project.name)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(isSelected ? Color.white : Color.white.opacity(0.88))
                        .lineLimit(1)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 8, weight: .bold))
                        .rotationEffect(.degrees(expanded ? 90 : 0))
                        .foregroundStyle(isSelected ? Color.white.opacity(0.8) : Color.white.opacity(0.55))
                }
                .padding(.horizontal, 8)
                .frame(height: 28)
                .background(isSelected ? Color.geocentricAccent : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 5))
            }
            .buttonStyle(.plain)
            .pointerHover()
            .contextMenu {
                Button("New Thread in Project") {
                    appModel.selectProject(project.id)
                    appModel.newConversation()
                }
                Button("Reveal in Finder") {
                    NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: project.path)
                }
                Button("Open in Terminal") {
                    let process = Process()
                    process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                    process.arguments = ["-a", "Terminal", project.path]
                    try? process.run()
                }
                Button("Open Folder") {
                    NSWorkspace.shared.open(URL(fileURLWithPath: project.path))
                }
                Divider()
                Button("Remove Project", role: .destructive) {
                    appModel.removeProject(project.id)
                }
            }

            if expanded {
                if conversations.isEmpty {
                    Text("No threads yet")
                        .font(.system(size: 11, weight: .light))
                        .foregroundStyle(Color.white.opacity(0.55))
                        .padding(.leading, 24)
                        .frame(height: 24)
                } else {
                    ForEach(conversations) { conversation in
                        let isSelected = appModel.selectedConversationID == conversation.id
                        Button {
                            appModel.selectProject(project.id)
                            appModel.selectConversation(conversation.id)
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: "bubble.left")
                                    .font(.system(size: 10))
                                    .foregroundStyle(isSelected ? Color.white : Color.white.opacity(0.65))
                                Text(conversation.title)
                                    .font(.system(size: 12.5))
                                    .foregroundStyle(isSelected ? Color.white : Color.white.opacity(0.85))
                                    .lineLimit(1)
                                Spacer()
                            }
                            .padding(.leading, 20)
                            .padding(.trailing, 8)
                            .frame(height: 26)
                            .background(isSelected ? Color.geocentricAccent : Color.clear)
                            .clipShape(RoundedRectangle(cornerRadius: 5))
                        }
                        .buttonStyle(.plain)
                        .pointerHover()
                        .contextMenu {
                            Button("Rename Thread...") {
                                renameConversationPrompt(conversation)
                            }
                            Button("Export Thread...") {
                                appModel.exportConversation(conversation)
                            }
                            Button("Delete Thread", role: .destructive) {
                                appModel.deleteConversation(conversation.id)
                            }
                        }
                    }
                }
            }
        }
    }

    private func renameConversationPrompt(_ conversation: Conversation) {
        let alert = NSAlert()
        alert.messageText = "Rename Thread"
        alert.informativeText = "Enter a new title for this conversation:"
        alert.addButton(withTitle: "Rename")
        alert.addButton(withTitle: "Cancel")
        
        let textField = NSTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24))
        textField.stringValue = conversation.title
        alert.accessoryView = textField
        
        if alert.runModal() == .alertFirstButtonReturn {
            let newTitle = textField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if !newTitle.isEmpty {
                if let index = appModel.conversations.firstIndex(where: { $0.id == conversation.id }) {
                    appModel.conversations[index].title = newTitle
                    appModel.saveConversations()
                }
            }
        }
    }
}
