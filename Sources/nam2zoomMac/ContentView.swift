import SwiftUI
import AppKit
import Foundation
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var vm: AppViewModel

    var body: some View {
        VStack(spacing: 0) {
            if let startupError = vm.startupError {
                Text("nam2zoom could not locate its tools/ folder: \(startupError)")
                    .font(.callout)
                    .foregroundStyle(.red)
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.red.opacity(0.1))
            }
            HSplitView {
                WorkspaceView(vm: vm)
                    .frame(minWidth: 560, idealWidth: 760)
                DetailPanel(vm: vm)
                    .frame(minWidth: 280, idealWidth: 320, maxWidth: 380)
            }
            Divider()
            ActivityView(vm: vm)
                .frame(minHeight: 170, idealHeight: 200, maxHeight: 260)
        }
        .onDrop(of: [.fileURL], isTargeted: nil) { providers in
            handleDrop(providers)
            return true
        }
    }

    private func handleDrop(_ providers: [NSItemProvider]) {
        var urls: [URL] = []
        let group = DispatchGroup()
        for provider in providers {
            group.enter()
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                if let url { urls.append(url) }
                group.leave()
            }
        }
        group.notify(queue: .main) {
            Task { await vm.addPaths(urls) }
        }
    }
}

private struct WorkspaceView: View {
    @ObservedObject var vm: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Model workspace").font(.title2).bold()
                Text("Add NAM models, organize your slots, then build a custom pedal effect.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 8) {
                Button("+  Add model") { addFromDialog() }
                    .keyboardShortcut("o")
                Button("Open list") { Task { await vm.openProject() } }
                Button("Save list") { vm.saveProject() }
                Divider().frame(height: 18)
                Button("Move up") { vm.moveSelected(-1) }
                    .disabled(vm.busy || (vm.selectedIndex ?? 0) <= 0)
                Button("Move down") { vm.moveSelected(1) }
                    .disabled(vm.busy || vm.selectedIndex == nil || vm.selectedIndex! >= vm.models.count - 1)
                Button("Remove") { vm.removeSelected() }
                    .disabled(vm.busy || vm.selectedIndex == nil)
                    .foregroundStyle(.red)
            }
            .disabled(vm.busy)

            ModelTable(vm: vm)
                .frame(minHeight: 220)

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Epochs").foregroundStyle(.secondary)
                    Stepper(value: $vm.epochs, in: 1...300) {
                        Text("\(vm.epochs)").monospacedDigit().frame(width: 40)
                    }
                    .disabled(vm.busy)
                    Toggle("Best effort", isOn: $vm.bestEffort)
                        .disabled(vm.busy)
                        .help("Allow lower-fidelity NAM conversions after training; device safety checks remain required")
                    Toggle("Back up device", isOn: $vm.backupEnabled)
                        .disabled(vm.busy)
                        .help("Save a full pedal backup before installing or uninstalling")
                    Spacer()
                }
                HStack {
                    Button("Build effect") { Task { await vm.build(installAfterBuild: false) } }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!vm.canBuild)
                    Button("Build + Install") { Task { await vm.build(installAfterBuild: true) } }
                        .disabled(!vm.canBuild)
                        .tint(.blue)
                    Button("Uninstall from pedal") { Task { await vm.uninstall() } }
                        .disabled(!vm.canUninstall)
                    Button("Open A/B") { vm.openPreview() }
                        .disabled(vm.busy || vm.previewRoot == nil)
                    Spacer()
                }
            }
        }
        .padding(16)
    }

    private func addFromDialog() {
        let panel = NSOpenPanel()
        panel.title = "Add NAM models"
        panel.allowedContentTypes = [UTType(filenameExtension: "nam") ?? .data]
        panel.allowsMultipleSelection = true
        if panel.runModal() == .OK {
            Task { await vm.addPaths(panel.urls) }
        }
    }
}

private struct ModelTable: View {
    @ObservedObject var vm: AppViewModel

    var body: some View {
        Table(vm.models, selection: $vm.selectedID) {
            TableColumn("#") { model in
                if let idx = vm.models.firstIndex(where: { $0.id == model.id }) {
                    Text(String(format: "%02d", idx + 1))
                }
            }.width(32)
            TableColumn("Pedal label") { model in Text(model.label) }.width(90)
            TableColumn("NAM model") { model in
                Text(model.fileName).lineLimit(1).truncationMode(.middle)
            }
            TableColumn("Compatibility") { model in
                Text(model.status.display)
                    .foregroundStyle(color(for: model.status))
            }.width(140)
        }
    }

    private func color(for status: Compatibility) -> Color {
        switch status {
        case .ready, .adapt: return .green
        case .unsupported: return .red
        case .checking: return .secondary
        }
    }
}
