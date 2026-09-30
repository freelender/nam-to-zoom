import Foundation

enum Compatibility: String {
    case checking = "Checking"
    case ready = "Ready"
    case adapt = "Adapt"
    case unsupported = "Unsupported"

    var display: String {
        switch self {
        case .checking: return "Checking"
        case .ready: return "Compatible"
        case .adapt: return "Conversion needed"
        case .unsupported: return "Unsupported"
        }
    }
}

struct ModelEntry: Identifiable {
    let id = UUID()
    var path: URL
    var label: String
    var irPath: URL?
    var status: Compatibility = .checking
    var sampleRate: Int = 0

    var fileName: String { path.lastPathComponent }
}

/// Codable snapshot used for saving/opening `.n2zbank.json` project lists,
/// matching the WinForms app's on-disk field names so lists stay interchangeable.
struct ModelEntrySnapshot: Codable {
    var Path: String
    var Label: String
    var IrPath: String?
}
