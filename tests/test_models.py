import unittest
from unittest.mock import patch
import subprocess

from omnifetch.engines import StreamlinkEngine, YtDlpEngine
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



class EngineProbeTests(unittest.TestCase):
    def completed(self, args, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    @patch("omnifetch.engines._which", return_value="/usr/bin/yt-dlp")
    @patch("omnifetch.engines._run")
    def test_ytdlp_probe_does_not_use_deprecated_no_call_home(self, run, _which):
        run.return_value = self.completed(
            ["yt-dlp"], stdout='{"title":"Example","formats":[{}]}'
        )
        result = YtDlpEngine().probe("https://example.com/video")
        self.assertEqual(result.status, "READY")
        command = run.call_args.args[0]
        self.assertNotIn("--no-call-home", command)

    @patch("omnifetch.engines._which", return_value="/usr/bin/streamlink")
    @patch("omnifetch.engines._run")
    def test_streamlink_requires_successful_stream_resolution(self, run, _which):
        run.side_effect = [
            self.completed(["streamlink", "--can-handle-url"], stdout=""),
            self.completed(["streamlink", "--stream-url"], stdout="https://cdn.example/video.m3u8\\n"),
        ]
        result = StreamlinkEngine().probe("https://example.com/live")
        self.assertEqual(result.status, "READY")
        self.assertTrue(result.supported)
        self.assertTrue(result.metadata["stream_resolved"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][1:3], ["--stream-url", "https://example.com/live"])

    @patch("omnifetch.engines._which", return_value="/usr/bin/streamlink")
    @patch("omnifetch.engines._run")
    def test_streamlink_plugin_match_is_not_a_ready_candidate(self, run, _which):
        run.side_effect = [
            self.completed(["streamlink", "--can-handle-url"]),
            self.completed(["streamlink", "--stream-url"], returncode=1, stderr="429 Too Many Requests"),
        ]
        result = StreamlinkEngine().probe("https://example.com/live")
        self.assertEqual(result.status, "PLUGIN_MATCH")
        self.assertFalse(result.supported)
        self.assertIn("could not resolve", result.message)
        self.assertTrue(result.metadata["plugin_match"])
        self.assertFalse(result.metadata["stream_resolved"])

if __name__ == "__main__":
    unittest.main()
