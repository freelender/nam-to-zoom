import SwiftUI
import AppKit

/// Quits the whole process (SwiftUI's WindowGroup otherwise keeps the app
/// running in the background after the last window closes) and makes sure
/// no python/core_render subprocess is left orphaned behind it.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        PythonRunner.terminateAllActive()
    }
}

@main
struct nam2zoomMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var viewModel = AppViewModel()

    var body: some Scene {
        WindowGroup("nam2zoom") {
            ContentView(vm: viewModel)
                .frame(minWidth: 1080, minHeight: 720)
        }
        .windowResizability(.contentSize)
    }
}
