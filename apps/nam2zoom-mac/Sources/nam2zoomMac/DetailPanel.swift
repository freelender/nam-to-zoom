import SwiftUI
import Foundation

struct DetailPanel: View {
    @ObservedObject var vm: AppViewModel

    private var selected: ModelEntry? {
        guard let idx = vm.selectedIndex else { return nil }
        return vm.models[idx]
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Selected model").font(.title3).bold()

                if let model = selected {
                    Group {
                        Text("NAM file").font(.caption).foregroundStyle(.secondary)
                        Text(model.fileName).font(.headline).lineLimit(1).truncationMode(.middle)
                        Text(model.path.path).font(.caption).foregroundStyle(.secondary)
                            .lineLimit(1).truncationMode(.middle)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Pedal label").font(.caption).foregroundStyle(.secondary)
                        TextField("", text: labelBinding(for: model.id))
                            .textFieldStyle(.roundedBorder)
                            .background(vm.labelsValid() ? Color.clear : Color.red.opacity(0.15))
                        HStack {
                            Spacer()
                            Text("\(model.label.count)/5").font(.caption).foregroundStyle(.secondary)
                        }
                    }

                    Text("Compatibility: \(model.status.display)")
                        .foregroundStyle(color(for: model.status))
                    Text(model.sampleRate == 0 ? "Sample rate: Unknown"
                        : "Sample rate: \(String(format: "%.1f", Double(model.sampleRate) / 1000)) kHz")
                    Text(fileSizeText(model.path))

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Cab IR (optional)").font(.caption).foregroundStyle(.secondary)
                        HStack {
                            Button("Choose WAV") { vm.chooseIr(for: model.id) }
                                .disabled(vm.busy)
                            Button("Clear") { vm.clearIr(for: model.id) }
                                .disabled(vm.busy || model.irPath == nil)
                        }
                        Text(model.irPath?.path ?? "No IR selected")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .truncationMode(.middle)
                    }
                } else {
                    Text("No model selected")
                        .font(.headline)
                    Text("Select a model from the list to view its details and settings.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }

                Spacer()
            }
            .padding(16)
        }
    }

    private func labelBinding(for id: ModelEntry.ID) -> Binding<String> {
        Binding(
            get: { vm.models.first(where: { $0.id == id })?.label ?? "" },
            set: { vm.setLabel($0, forSelected: id) }
        )
    }

    private func color(for status: Compatibility) -> Color {
        switch status {
        case .ready, .adapt: return .green
        case .unsupported: return .red
        case .checking: return .secondary
        }
    }

    private func fileSizeText(_ url: URL) -> String {
        guard let size = try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber else {
            return "File size: Missing file"
        }
        return "File size: \(String(format: "%.1f", size.doubleValue / 1024)) KB"
    }
}
