import SwiftUI
import UniformTypeIdentifiers
import AppKit

struct TestPickerView: View {
    var body: some View {
        Button("Select file") {
            let panel = NSOpenPanel()
            panel.allowedContentTypes = [.json]
            panel.begin { response in
                print("Selected")
            }
        }
    }
}
