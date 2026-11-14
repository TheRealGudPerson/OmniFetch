import unittest

from omnifetch.models import ProbeResult, safe_filename, validate_url


class URLValidationTests(unittest.TestCase):
    def test_accepts_http_and_https(self):
        self.assertEqual(validate_url("https://example.com/video"), "https://example.com/video")
        self.assertEqual(validate_url("http://example.com/file.mp4"), "http://example.com/file.mp4")

    def test_rejects_non_http_schemes(self):
        for value in ("file:///etc/passwd", "ftp://example.com/video", "javascript:alert(1)"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_url(value)

    def test_rejects_missing_hostname(self):
        with self.assertRaises(ValueError):
            validate_url("https:///missing-host")


class FilenameTests(unittest.TestCase):
    def test_removes_path_and_control_characters(self):
        name = safe_filename("../../bad:name\nvideo.mp4")
        self.assertNotIn("/", name)
        self.assertNotIn(":", name)
        self.assertNotIn("\n", name)

    def test_uses_fallback_for_empty_name(self):
        self.assertEqual(safe_filename("  "), "omnifetch-download")


class ProbeResultTests(unittest.TestCase):
    def test_serializes_to_plain_dictionary(self):
        result = ProbeResult("yt-dlp", "READY", True, 100, "recognized", {"title": "Example"})
        data = result.to_dict()
        self.assertEqual(data["engine"], "yt-dlp")
        self.assertEqual(data["metadata"]["title"], "Example")


if __name__ == "__main__":
    unittest.main()
