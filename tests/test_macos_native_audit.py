"""Universal Mach-O headers must not be mistaken for native dependencies."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "release"))
from verify_portable import macos_library_names, nonportable_macos_libraries


class MacosNativeAuditTests(unittest.TestCase):
    def test_universal_harfbuzz_headers_with_spaces(self):
        filename = "/var/folders/tmp/app with spaces/nam2zoom.app/Contents/MacOS/libHarfBuzzSharp.dylib"
        records = "\t@rpath/libHarfBuzzSharp.dylib (compatibility version 0.0.0, current version 0.0.0)\n"
        records += "\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 120.1.0)\n"
        records += "\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1319.0.0)\n"
        output = f"{filename} (architecture x86_64):\n{records}{filename} (architecture arm64):\n{records}"
        # Regression: the previous parser rejected the second filename header.
        old_names = [line.strip().split(" (", 1)[0] for line in output.splitlines()[1:]]
        self.assertIn(filename, old_names)
        self.assertEqual(nonportable_macos_libraries(output), [])
        self.assertEqual(len(list(macos_library_names(output))), 6)

    def test_bad_dependency_in_second_architecture_remains_blocked(self):
        output = """/tmp/lib.dylib (architecture x86_64):
\t@rpath/lib.dylib (compatibility version 1.0.0, current version 1.0.0)
/tmp/lib.dylib (architecture arm64):
\t/opt/homebrew/lib/libbad.dylib (compatibility version 1.0.0, current version 1.0.0)
"""
        self.assertEqual(nonportable_macos_libraries(output), ["/opt/homebrew/lib/libbad.dylib"])

    def test_absolute_install_id_not_exempted_even_when_it_matches_filename(self):
        filename = "/Users/runner/work/build/libexample.dylib"
        output = f"{filename}:\n\t{filename} (compatibility version 1.0.0, current version 1.0.0)\n"
        self.assertEqual(nonportable_macos_libraries(output), [filename])

    def test_thin_binary_system_framework_and_loader_paths(self):
        names = ["/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation",
                 "@loader_path/../lib/libpython3.12.dylib", "@executable_path/libexample.dylib"]
        output = "/tmp/python:\n" + "".join(f"    {name} (compatibility version 1.0.0, current version 1.0.0)\n" for name in names)
        self.assertEqual(list(macos_library_names(output)), names)
        self.assertEqual(nonportable_macos_libraries(output), [])

    def test_paths_with_parentheses_and_unexpected_records(self):
        name = "/Users/build (local)/libbad.dylib"
        output = f"/tmp/library:\n\t{name} (compatibility version 1.0.0, current version 1.0.0)\n"
        self.assertEqual(nonportable_macos_libraries(output), [name])
        with self.assertRaisesRegex(RuntimeError, "Unexpected otool"):
            list(macos_library_names("/tmp/library:\n\tunexpected record\n"))


if __name__ == "__main__":
    unittest.main()
