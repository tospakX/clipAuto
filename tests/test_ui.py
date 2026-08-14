import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from youtube_clipper.dependencies import DependencyError, DependencyReport
from youtube_clipper.ui_server import JobManager, create_server, validate_youtube_url


class URLValidationTests(unittest.TestCase):
    def test_accepts_supported_youtube_hosts(self):
        self.assertEqual(
            validate_youtube_url(" https://www.youtube.com/watch?v=abc "),
            "https://www.youtube.com/watch?v=abc",
        )
        self.assertEqual(
            validate_youtube_url("https://youtu.be/abc?t=30"),
            "https://www.youtube.com/watch?v=abc",
        )

    def test_rejects_non_youtube_and_lookalike_hosts(self):
        for value in (
            "",
            "not a url",
            "https://example.com/video",
            "https://youtube.com.evil.test/x",
            "https://youtube.com/",
            "https://youtube.com/watch?list=playlist",
            "https://youtu.be/%C3%A9",
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
                output = root / "video-example" / "clips" / "01_topic.mp4"
                output.parent.mkdir(parents=True)
                output.write_bytes(b"video")
                callback(100, "Your clips are ready")
                return [output]

            manager = JobManager(root, root / "work", pipeline_runner=runner)
            started = manager.start("https://youtu.be/example", 1.25, "small")
            job = self._wait(manager, str(started["id"]))

            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["progress"], 100)
            self.assertEqual(job["clips"][0]["name"], "01_topic.mp4")
            self.assertGreaterEqual(len(job["events"]), 3)

    def test_multiple_jobs_run_sequentially_and_second_waits(self):
        release = threading.Event()
        first_started = threading.Event()
        calls = []

        def runner(url, *_args):
            calls.append(url)
            if url.endswith("first"):
                first_started.set()
                release.wait(2)
            return []

        manager = JobManager(pipeline_runner=runner)
        submission = manager.enqueue(
            ["https://youtu.be/first", "https://youtu.be/second"], 1.0, "small"
        )
        self.assertTrue(first_started.wait(1))
        second_id = str(submission["jobs"][1]["id"])
        self.assertEqual(manager.get(second_id)["status"], "waiting")
        release.set()
        jobs = self._wait_all(manager, [str(item["id"]) for item in submission["jobs"]])

        self.assertEqual(calls, [
            "https://www.youtube.com/watch?v=first",
            "https://www.youtube.com/watch?v=second",
        ])
        self.assertEqual([job["status"] for job in jobs], ["completed", "completed"])

    def test_failed_middle_job_does_not_stop_later_items(self):
        calls = []

        def runner(url, *_args):
            calls.append(url)
            if url.endswith("dead"):
                raise RuntimeError("video unavailable")
            return []

        manager = JobManager(pipeline_runner=runner)
        with self.assertLogs("youtube_clipper.ui_server", level="ERROR"):
            submission = manager.enqueue(
                [
                    "https://youtu.be/first",
                    "https://youtu.be/dead",
                    "https://youtu.be/third",
                ],
                1.0,
                "small",
            )
            jobs = self._wait_all(manager, [str(item["id"]) for item in submission["jobs"]])

        self.assertEqual([job["status"] for job in jobs], ["completed", "failed", "completed"])
        self.assertEqual(len(calls), 3)

    def test_duplicate_video_ids_are_not_added_twice(self):
        release = threading.Event()

        def runner(*_args):
            release.wait(2)
            return []

        manager = JobManager(pipeline_runner=runner)
        submission = manager.enqueue(
            [
                "https://youtu.be/same-id?t=10",
                "https://www.youtube.com/watch?v=same-id&feature=share",
            ],
            1.0,
            "small",
        )
        duplicate = manager.enqueue(["https://youtube.com/shorts/same-id"], 1.0, "small")
        release.set()

        self.assertEqual(len(submission["jobs"]), 1)
        self.assertEqual(len(submission["duplicates"]), 1)
        self.assertEqual(duplicate["jobs"], [])
        self.assertEqual(len(duplicate["duplicates"]), 1)

    def test_waiting_job_can_be_removed(self):
        release = threading.Event()
        first_started = threading.Event()

        def runner(url, *_args):
            if url.endswith("first"):
                first_started.set()
                release.wait(2)
            return []

        manager = JobManager(pipeline_runner=runner)
        submission = manager.enqueue(
            ["https://youtu.be/first", "https://youtu.be/remove-me"], 1.0, "small"
        )
        self.assertTrue(first_started.wait(1))
        waiting_id = str(submission["jobs"][1]["id"])

        self.assertTrue(manager.remove(waiting_id))
        self.assertIsNone(manager.get(waiting_id))
        release.set()
        first_id = str(submission["jobs"][0]["id"])
        self._wait(manager, first_id)

    def test_progress_maps_to_analyzing_and_clipping_states(self):
        analyzing = threading.Event()
        clipping = threading.Event()
        continue_to_clipping = threading.Event()
        finish = threading.Event()

        def runner(*args):
            callback = args[-1]
            callback(30, "Transcribing locally")
            analyzing.set()
            continue_to_clipping.wait(2)
            callback(90, "Exporting clip 1 of 1")
            clipping.set()
            finish.wait(2)
            return []

        manager = JobManager(pipeline_runner=runner)
        job_id = str(manager.start("https://youtu.be/stages", 1.0, "small")["id"])
        self.assertTrue(analyzing.wait(1))
        self.assertEqual(manager.get(job_id)["status"], "analyzing")
        continue_to_clipping.set()
        self.assertTrue(clipping.wait(1))
        self.assertEqual(manager.get(job_id)["status"], "clipping")
        finish.set()
        self.assertEqual(self._wait(manager, job_id)["status"], "completed")

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

    @classmethod
    def _wait_all(cls, manager, job_ids):
        return [cls._wait(manager, job_id) for job_id in job_ids]


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
        self.assertIn(b"Build your queue", home)
        self.assertIn(b"9:16", home)
        for speed in (b"0.50", b"0.75", b"1.00", b"1.25", b"1.50", b"1.75", b"2.00"):
            with self.subTest(speed=speed):
                self.assertIn(speed, home)
        self.assertIn(b"--acid", self._get("/assets/app.css"))
        health = json.loads(self._get("/api/health"))
        self.assertTrue(health["ready"])
        self.assertEqual(health["models"], ["test-model"])
        self.assertEqual(health["warnings"], [])

    def test_home_exposes_multi_link_composer_and_queue(self):
        home = self._get("/")

        self.assertIn(b'id="youtubeUrls"', home)
        self.assertIn(b'id="queueList"', home)
        self.assertIn(b"one link per line", home.lower())

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
                {
                    "urls": ["https://youtu.be/example"],
                    "speed": 1.0,
                    "whisper_model": "small",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        submission = json.loads(urllib.request.urlopen(request, timeout=2).read())
        started = submission["jobs"][0]
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

    def test_multi_add_list_duplicate_and_waiting_delete(self):
        release = threading.Event()
        first_started = threading.Event()

        def blocking_runner(url, *_args):
            if url.endswith("first"):
                first_started.set()
                release.wait(2)
            return []

        self.server.manager.pipeline_runner = blocking_runner
        request = urllib.request.Request(
            f"{self.base}/api/jobs",
            data=json.dumps(
                {
                    "urls": [
                        "https://youtu.be/first",
                        "https://youtu.be/second",
                        "https://www.youtube.com/watch?v=second",
                    ],
                    "speed": 1.0,
                    "whisper_model": "small",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        submission = json.loads(urllib.request.urlopen(request, timeout=2).read())
        self.assertTrue(first_started.wait(1))

        self.assertEqual(len(submission["jobs"]), 2)
        self.assertEqual(len(submission["duplicates"]), 1)
        queue = json.loads(self._get("/api/jobs"))
        self.assertEqual([item["status"] for item in queue["jobs"]], ["downloading", "waiting"])

        waiting_id = submission["jobs"][1]["id"]
        delete = urllib.request.Request(
            f"{self.base}/api/jobs/{waiting_id}",
            method="DELETE",
        )
        removed = json.loads(urllib.request.urlopen(delete, timeout=2).read())
        self.assertTrue(removed["removed"])
        self.assertEqual(len(json.loads(self._get("/api/jobs"))["jobs"]), 1)
        release.set()

    def test_urls_payload_must_be_a_bounded_list_of_strings(self):
        for urls in ("https://youtu.be/example", [], ["https://youtu.be/example"] * 101):
            request = urllib.request.Request(
                f"{self.base}/api/jobs",
                data=json.dumps({"urls": urls}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.subTest(urls_type=type(urls).__name__), self.assertRaises(
                urllib.error.HTTPError
            ) as caught:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 400)

    def _get(self, path):
        with urllib.request.urlopen(f"{self.base}{path}", timeout=2) as response:
            return response.read()


if __name__ == "__main__":
    unittest.main()
