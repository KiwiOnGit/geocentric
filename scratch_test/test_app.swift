import SwiftUI

@main
struct TestApp: App {
    var body: some Scene {
        WindowGroup {
            VStack {
                Text("Hello, SwiftUI Compiled via CLI!")
                    .padding()
            }
            .frame(width: 300, height: 200)
        }
    }
}
