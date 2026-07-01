import SwiftUI
import AppKit
import Combine
import Foundation
import Darwin

@main
struct GeocentricApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var server = DesktopServer.shared
    @StateObject private var ollama = OllamaManager.shared
    @StateObject private var appModel = NativeAppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(server)
                .environmentObject(ollama)
                .environmentObject(appModel)
                .frame(minWidth: 1180, minHeight: 760)
                .background(Color.geocentricCanvas)
                .onAppear {
                    appModel.attach(server: server, ollama: ollama)
                    ollama.bootstrap()
                }
        }
        .windowStyle(.hiddenTitleBar)
        .windowToolbarStyle(.unifiedCompact)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Conversation") {
                    NativeAppModel.sharedReference?.newConversation()
                }
                .keyboardShortcut("n", modifiers: [.command])
            }

            CommandMenu("Conversation") {
                Button("Retry Last Message") {
                    NativeAppModel.sharedReference?.retryLastUserMessage()
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

                Button("Export Conversation...") {
                    NativeAppModel.sharedReference?.exportConversation()
                }
                .keyboardShortcut("e", modifiers: [.command, .shift])

                Button("Compact Context") {
                    NativeAppModel.sharedReference?.compactContext()
                }
                .keyboardShortcut("k", modifiers: [.command, .shift])

                Button("Stop Response") {
                    NativeAppModel.sharedReference?.stopResponse()
                }
                .keyboardShortcut(.escape, modifiers: [])
            }
        }
    }
}
