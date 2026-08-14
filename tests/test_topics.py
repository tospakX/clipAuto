import unittest

from youtube_clipper.topics import topic_names
from youtube_clipper.types import BoundarySuggestion, TranscriptSegment, VideoTimestamp


class TopicNameTests(unittest.TestCase):
    def test_prefers_creator_titles_then_semantic_reasons_then_transcript(self):
        names = topic_names(
            [0.0, 30.0, 60.0, 90.0],
            (
                VideoTimestamp(0, "Introduction", 0.95),
                VideoTimestamp(30, "Camera Setup", 0.95),
            ),
            [BoundarySuggestion(60.5, 0.9, "Advanced editing workflow")],
            [TranscriptSegment(90, 95, "Publish consistently for better audience growth")],
        )

        self.assertEqual(
            names,
            [
                "introduction",
                "camera-setup",
                "advanced-editing-workflow",
                "publish-consistently-for-better-audience-growth",
            ],
        )

    def test_uses_numbered_fallback_for_empty_or_repeated_names(self):
        names = topic_names(
            [0.0, 30.0, 60.0],
            (),
            (),
            [
                TranscriptSegment(0, 5, "Music"),
                TranscriptSegment(30, 35, "Music"),
            ],
        )

        self.assertEqual(names, ["music", "music-2", "topic-03"])

    def test_topic_names_are_safe_and_bounded(self):
        names = topic_names(
            [0.0],
            (VideoTimestamp(0, 'AUX / "unsafe" : title? ' + "x" * 200),),
            (),
            (),
        )

        self.assertLessEqual(len(names[0]), 64)
        self.assertRegex(names[0], r"^[a-z0-9._-]+$")


if __name__ == "__main__":
    unittest.main()
