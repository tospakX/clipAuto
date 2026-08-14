import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_clipper.cli import main


class BatchCLITests(unittest.TestCase):
    @patch("youtube_clipper.cli.run_pipeline")
    def test_processes_every_url_and_returns_failure_if_one_item_fails(self, run_pipeline):
        run_pipeline.side_effect = [
            [Path("output/first/clips/01_topic.mp4")],
            RuntimeError("dead video"),
            [Path("output/third/clips/01_topic.mp4")],
        ]

        with self.assertLogs(level="ERROR") as logs:
            result = main(
                [
                    "https://youtu.be/first01",
                    "https://youtu.be/dead002",
                    "https://youtu.be/third03",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(
            [call.args[0] for call in run_pipeline.call_args_list],
            [
                "https://youtu.be/first01",
                "https://youtu.be/dead002",
                "https://youtu.be/third03",
            ],
        )
        self.assertIn("dead video", logs.output[0])

    @patch("youtube_clipper.cli.run_pipeline", return_value=[])
    def test_single_url_usage_remains_supported(self, run_pipeline):
        result = main(["https://youtu.be/single1", "--speed", "1.5"])

        self.assertEqual(result, 0)
        self.assertEqual(run_pipeline.call_count, 1)
        self.assertEqual(run_pipeline.call_args.args[0], "https://youtu.be/single1")
        self.assertEqual(run_pipeline.call_args.args[3], 1.5)


if __name__ == "__main__":
    unittest.main()
