// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "nam2zoom-mac",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "nam2zoomMac",
            path: "Sources/nam2zoomMac",
            resources: [.copy("Resources/TRAINING_DI.wav")]
        )
    ]
)
