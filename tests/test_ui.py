import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from youtube_clipper.dependencies import DependencyError, DependencyReport
from youtube_clipper.ui_server import JobBusyError, JobManager, create_server, validate_youtube_url


class URLValidationTests(unittest.TestCase):
    def test_accepts_supported_youtube_hosts(self):
        self.assertEqual(
            validate_youtube_url(" https://www.youtube.com/watch?v=abc "),
            "https://www.youtube.com/watch?v=abc",
        )
        self.assertEqual(validate_youtube_url("https://youtu.be/abc"), "https://youtu.be/abc")

    def test_rejects_non_youtube_and_lookalike_hosts(self):
        for value in (
            "",
            "not a url",
            "https://example.com/video",
            "https://youtube.com.evil.test/x",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_youtube_url(value)


class JobManagerTests(unittest.TestCase):
    def test_job_reports_progress_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def runner(*args):
                callback = args[-1]
                callback(30, "Transcribing speech locally")
                output = root / "part_01.mp4"
                output.write_bytes(b"video")
                callback(100, "Your clips are ready")
                return [output]

            manager = JobManager(root, root / "work", pipeline_runner=runner)
            started = manager.start("https://youtu.be/example", 1.25, "small")
            job = self._wait(manager, str(started["id"]))

            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["progress"], 100)
            self.assertEqual(job["clips"][0]["name"], "part_01.mp4")
            self.assertGreaterEqual(len(job["events"]), 3)

    def test_rejects_second_concurrent_job(self):
        release = threading.Event()

        def runner(*_args):
            release.wait(2)
            return []

        manager = JobManager(pipeline_runner=runner)
        manager.start("https://youtu.be/first", 1.0, "small")
        try:
            with self.assertRaises(JobBusyError):
                manager.start("https://youtu.be/second", 1.0, "small")
        finally:
            release.set()

    def test_failed_job_keeps_clear_error(self):
        def runner(*_args):
            raise RuntimeError("synthetic pipeline failure")

        manager = JobManager(pipeline_runner=runner)
        with self.assertLogs("youtube_clipper.ui_server", level="ERROR") as logs:
            started = manager.start("https://youtu.be/failure", 1.0, "small")
            job = self._wait(manager, str(started["id"]))
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["stage"], "Processing stopped")
        self.assertEqual(job["error"], "synthetic pipeline failure")
        self.assertIn("UI clipping job", logs.output[0])

    @staticmethod
    def _wait(manager, job_id):
        for _ in range(100):
            job = manager.get(job_id)
            if job and job["status"] in {"completed", "failed"}:
                return job
            time.sleep(0.01)
        raise AssertionError("job did not finish")


class HTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)

        def runner(*args):
            output_dir = args[1]
            callback = args[-1]
            callback(50, "Halfway there")
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / "part_01.mp4"
            output.write_bytes(b"0123456789")
            callback(100, "Your clips are ready")
            return [output]

        self.server = create_server(
            port=0,
            output_dir=root / "output",
            work_dir=root / "work",
            pipeline_runner=runner,
            dependency_checker=lambda _url: DependencyReport(("test-model",)),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def test_home_assets_and_health(self):
        home = self._get("/")
        self.assertIn(b"LocalCut", home)
        self.assertIn(b"Create clips", home)
        self.assertIn(b"9:16", home)
        for speed in (b"0.50", b"0.75", b"1.00", b"1.25", b"1.50", b"1.75", b"2.00"):
            with self.subTest(speed=speed):
                self.assertIn(speed, home)
        self.assertIn(b"--acid", self._get("/assets/app.css"))
        health = json.loads(self._get("/api/health"))
        self.assertTrue(health["ready"])
        self.assertEqual(health["models"], ["test-model"])
        self.assertEqual(health["warnings"], [])

    def test_invalid_submission_returns_clear_400(self):
        request = urllib.request.Request(
            f"{self.base}/api/jobs",
            data=json.dumps({"url": "https://example.com"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("valid youtube.com", caught.exception.read().decode())

    def test_unsupported_speed_returns_clear_400(self):
        request = urllib.request.Request(
            f"{self.base}/api/jobs",
            data=json.dumps(
                {"url": "https://youtu.be/example", "speed": 1.1, "whisper_model": "small"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("Speed must be one of", caught.exception.read().decode())

    def test_health_failure_returns_setup_details(self):
        def unavailable(_url):
            raise DependencyError("Ollama is not running")

        self.server.dependency_checker = unavailable
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.base}/api/health", timeout=2)
        self.assertEqual(caught.exception.code, 503)
        payload = json.loads(caught.exception.read())
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["message"], "Ollama is not running")

    def test_job_api_and_video_byte_ranges(self):
        request = urllib.request.Request(
            f"{self.base}/api/jobs",
            data=json.dumps(
                {"url": "https://youtu.be/example", "speed": 1.0, "whisper_model": "small"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = json.loads(urllib.request.urlopen(request, timeout=2).read())
        for _ in range(100):
            job = json.loads(self._get(f"/api/jobs/{started['id']}"))
            if job["status"] == "completed":
                break
            time.sleep(0.01)
        else:
            self.fail("HTTP job did not complete")

        clip_request = urllib.request.Request(
            f"{self.base}{job['clips'][0]['url']}", headers={"Range": "bytes=2-5"}
        )
        with urllib.request.urlopen(clip_request, timeout=2) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
            self.assertEqual(response.read(), b"2345")

        suffix_request = urllib.request.Request(
            f"{self.base}{job['clips'][0]['url']}", headers={"Range": "bytes=-4"}
        )
        with urllib.request.urlopen(suffix_request, timeout=2) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 6-9/10")
            self.assertEqual(response.read(), b"6789")

    def _get(self, path):
        with urllib.request.urlopen(f"{self.base}{path}", timeout=2) as response:
            return response.read()


if __name__ == "__main__":
    unittest.main()
