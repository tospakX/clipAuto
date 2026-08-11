import unittest

from youtube_clipper.boundaries import find_marker_times, fuse_boundaries
from youtube_clipper.types import (
    BoundarySuggestion,
    TranscriptSegment,
    TranscriptWord,
    VideoTimestamp,
)


class MarkerTests(unittest.TestCase):
    def test_detects_numbered_and_topic_phrases(self):
        segments = [
            TranscriptSegment(0, 4, "Intro"),
            TranscriptSegment(10, 14, "Number two, improve the opening hook."),
            TranscriptSegment(20, 24, "Next topic is editing."),
            TranscriptSegment(30, 34, "3. Publish consistently."),
        ]
        self.assertEqual(find_marker_times(segments), [10, 20, 30])

    def test_detects_standalone_number(self):
        self.assertEqual(find_marker_times([TranscriptSegment(7, 8, "2")]), [7])

    def test_detects_multiple_markers_inside_one_whisper_segment(self):
        text = "Intro. Number one, hooks matter. Number two, edit tightly. Next topic, captions."
        times = find_marker_times([TranscriptSegment(0, 40, text)])
        self.assertEqual(len(times), 3)
        self.assertLess(times[0], times[1])
        self.assertLess(times[1], times[2])

    def test_uses_word_timestamp_for_marker_inside_shared_segment(self):
        words = (
            TranscriptWord(0, 1, " Intro."),
            TranscriptWord(10, 11, " Number"),
            TranscriptWord(11, 12, " one,"),
            TranscriptWord(12, 13, " hook."),
            TranscriptWord(20, 21, " Number"),
            TranscriptWord(21, 22, " two,"),
            TranscriptWord(22, 23, " edit."),
        )
        segment = TranscriptSegment(0, 23, "Intro. Number one, hook. Number two, edit.", words)
        self.assertEqual(find_marker_times([segment]), [10, 20])


class FusionTests(unittest.TestCase):
    def test_creator_topic_map_blocks_false_subtopic_near_end(self):
        chapters = (
            VideoTimestamp(0, "First story", 0.95),
            VideoTimestamp(115, "Second story", 0.95),
            VideoTimestamp(221, "Third story", 0.95),
            VideoTimestamp(355, "Fourth story", 0.95),
            VideoTimestamp(432, "Fifth story", 0.95),
            VideoTimestamp(502, "Final story", 0.95),
        )
        result = fuse_boundaries(
            [
                TranscriptSegment(502, 507, "The final story begins."),
                TranscriptSegment(517, 521, "Once it spread, people began speculating."),
            ],
            scene_times=[517.95],
            llm_suggestions=[BoundarySuggestion(517, 0.92, "the story becomes widely discussed")],
            duration=579.494,
            video_timestamps=chapters,
        )
        self.assertEqual(result, [0.0, 115, 221, 355, 432, 502])

    def test_description_chapters_create_boundaries_and_snap_to_scenes(self):
        result = fuse_boundaries(
            [TranscriptSegment(0, 5, "Introduction")],
            [29.5],
            [],
            duration=70,
            video_timestamps=(
                VideoTimestamp(0, "Intro", 0.95),
                VideoTimestamp(30, "Lighting", 0.95),
            ),
        )
        self.assertEqual(result, [0.0, 29.5])

    def test_lone_description_time_needs_support(self):
        hint = (VideoTimestamp(30, "Jump ahead", 0.5),)
        self.assertEqual(
            fuse_boundaries([], [], [], duration=60, video_timestamps=hint),
            [0.0],
        )
        self.assertEqual(
            fuse_boundaries([], [30], [], duration=60, video_timestamps=hint),
            [0.0, 30],
        )

    def test_combines_marker_llm_and_scene_and_snaps_to_cut(self):
        segments = [
            TranscriptSegment(0, 5, "Introduction"),
            TranscriptSegment(20, 25, "Number two, lighting matters."),
        ]
        result = fuse_boundaries(
            segments,
            scene_times=[19.5],
            llm_suggestions=[BoundarySuggestion(20.5, 0.9, "new numbered point")],
            duration=50,
        )
        self.assertEqual(result, [0.0, 19.5])

    def test_scene_changes_alone_do_not_create_topics(self):
        result = fuse_boundaries([], [10, 20, 30], [], duration=45)
        self.assertEqual(result, [0.0])

    def test_semantic_boundary_uses_scene_as_support(self):
        result = fuse_boundaries(
            [TranscriptSegment(0, 4, "Intro")],
            [31.0],
            [BoundarySuggestion(30.0, 0.8, "speaker changes topic")],
            duration=60,
        )
        self.assertEqual(result, [0.0, 31.0])

    def test_rejects_low_confidence_semantic_guess_without_support(self):
        result = fuse_boundaries(
            [TranscriptSegment(0, 4, "Intro")],
            [],
            [BoundarySuggestion(30.0, 0.1, "uncertain")],
            duration=60,
        )
        self.assertEqual(result, [0.0])

    def test_rejects_high_confidence_ollama_guess_without_independent_support(self):
        result = fuse_boundaries(
            [TranscriptSegment(0, 4, "Intro")],
            [],
            [BoundarySuggestion(30.0, 0.99, "model is confident")],
            duration=60,
        )
        self.assertEqual(result, [0.0])

    def test_rejects_tiny_first_and_last_clips(self):
        suggestions = [BoundarySuggestion(3), BoundarySuggestion(55)]
        self.assertEqual(fuse_boundaries([], [], suggestions, 60), [0.0])

    def test_trims_preamble_before_explicit_first_topic(self):
        segments = [
            TranscriptSegment(0, 5, "Welcome and introduction."),
            TranscriptSegment(10, 15, "Number one, write a hook."),
            TranscriptSegment(30, 35, "Number two, edit tightly."),
        ]
        self.assertEqual(fuse_boundaries(segments, [], [], 50), [10, 30])


if __name__ == "__main__":
    unittest.main()
