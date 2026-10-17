from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from resolve_font_doctor.font_files import read_font_faces_from_file
from resolve_font_doctor.font_names import normalize_name, candidate_variants
from resolve_font_doctor.google_fonts import parse_metadata
from resolve_font_doctor.installer import FontInstaller
from resolve_font_doctor.manual_sources import find_manual_source
from resolve_font_doctor.models import FontFace, FontNeed, PresetRef, ScanReport
from resolve_font_doctor.presets import PresetRoot, extract_font_names, scan_presets
from resolve_font_doctor.report import generate_html


class NameTests(unittest.TestCase):
    def test_normalization(self) -> None:
        self.assertEqual(normalize_name("Open Sans"), normalize_name("open-sans"))
        self.assertEqual(normalize_name("A&B"), "aandb")

    def test_variants(self) -> None:
        variants = candidate_variants("Open Sans Bold")
        self.assertIn("opensans", variants)
        self.assertIn("opensans", candidate_variants("Open Sans"))


class ExtractionTests(unittest.TestCase):
    def test_font_references(self) -> None:
        text = """
        Font = Input { Value = "Bebas Neue", },
        FontName = "Open Sans",
        SubtitleFont = Input { Value = "PingFang SC", },
        Help_Fonts = Input { Value = "not a real font", },
        font-family: 'Montserrat', sans-serif;
        """
        names = extract_font_names(text)
        self.assertEqual(set(names), {"Bebas Neue", "Open Sans", "PingFang SC", "Montserrat"})

    def test_ignores_paths_and_empty(self) -> None:
        names = extract_font_names(
            'Font = Input { Value = "", }, Font = "C:/Windows/Fonts/arial.ttf",'
        )
        self.assertEqual(names, [])


class ScannerTests(unittest.TestCase):
    def test_standalone_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Templates"
            (root / "Edit").mkdir(parents=True)
            (root / "Edit" / "Standalone.setting").write_text(
                'Font = Input { Value = "Bebas Neue", },', encoding="utf-8"
            )
            with zipfile.ZipFile(root / "Pack.drfx", "w") as archive:
                archive.writestr(
                    "Edit/Titles/Inside.setting",
                    'FontName = Input { Value = "Open Sans", },',
                )
                archive.writestr("readme.txt", "no font here")
            report = scan_presets([PresetRoot(root, "测试预设")])
            self.assertEqual(report.archive_count, 1)
            self.assertEqual(report.preset_count, 2)
            self.assertEqual(report.file_count, 2)
            self.assertEqual({n.name for n in report.needs}, {"Bebas Neue", "Open Sans"})
            self.assertEqual(report.errors, [])


class MetadataTests(unittest.TestCase):
    def test_parse(self) -> None:
        payload = '''name: "Fahkwang"
license: "OFL"
fonts {
  name: "Fahkwang"
  style: "normal"
  weight: 400
  filename: "Fahkwang-Regular.ttf"
  post_script_name: "Fahkwang-Regular"
}
fonts {
  name: "Fahkwang"
  style: "italic"
  weight: 400
  filename: "Fahkwang-Italic.ttf"
}
'''
        meta = parse_metadata(payload)
        self.assertEqual(meta["name"], "Fahkwang")
        self.assertEqual(meta["license"], "OFL")
        self.assertEqual([f["filename"] for f in meta["fonts"]], ["Fahkwang-Regular.ttf", "Fahkwang-Italic.ttf"])


class InstallerTests(unittest.TestCase):
    def test_known_face_is_skipped(self) -> None:
        face = FontFace(family="Example Sans", subfamily="Regular", full_name="Example Sans Regular")
        installer = FontInstaller([face])
        self.assertTrue(installer._already_known(face))
        other = FontFace(family="Example Sans", subfamily="Bold")
        self.assertFalse(installer._already_known(other))


class ManualSourceTests(unittest.TestCase):
    def test_known_and_unknown(self) -> None:
        self.assertIsNotNone(find_manual_source("Gilroy"))
        self.assertIsNotNone(find_manual_source("Helvetica Now Display"))
        self.assertIsNone(find_manual_source("Definitely Not A Font Xyz"))


class ReportTests(unittest.TestCase):
    def test_generate(self) -> None:
        report = ScanReport(
            roots=["C:/Templates"],
            preset_count=3,
            archive_count=1,
            needs=[
                FontNeed(
                    name="Fahkwang",
                    key="fahkwang",
                    refs=[PresetRef("Demo / Title.setting")],
                    status="downloadable",
                    detail="Google Fonts · OFL",
                )
            ],
        )
        page = generate_html(report)
        self.assertIn("达芬奇字体管家", page)
        self.assertIn("Fahkwang", page)
        self.assertIn("可自动下载", page)


class SystemFontTests(unittest.TestCase):
    def test_parse_windows_font_if_available(self) -> None:
        candidates = [
            Path(r"C:\Windows\Fonts\arial.ttf"),
            Path(r"C:\Windows\Fonts\segoeui.ttf"),
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            self.skipTest("no sample system font on this platform")
        faces = read_font_faces_from_file(path)
        self.assertTrue(faces)
        self.assertTrue(faces[0].family)


if __name__ == "__main__":
    unittest.main()
