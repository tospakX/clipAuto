import json
import unittest

from youtube_clipper.ollama import (
    OllamaBoundaryReasoner,
    _parse_boundary_response,
    _transcript_windows,
    choose_model,
)
from youtube_clipper.types import TranscriptSegment, VideoTimestamp


class ModelChoiceTests(unittest.TestCase):
    def test_long_transcripts_keep_the_middle_in_multiple_windows(self):
        segments = [
            TranscriptSegment(index * 10, index * 10 + 5, f"topic-{index} " + "x" * 80)
            for index in range(12)
        ]
        windows = _transcript_windows(segments, limit=300)
        joined = "\n".join(window.text for window in windows)

        self.assertGreater(len(windows), 1)
        self.assertIn("topic-0", joined)
        self.assertIn("topic-6", joined)
        self.assertIn("topic-11", joined)
        self.assertTrue(all(len(window.text) <= 300 for window in windows))

    def test_invalid_and_non_finite_model_items_are_ignored(self):
        content = json.dumps(
            {
                "boundaries": [
                    {"timestamp": 10, "confidence": 1.4, "reason": "valid"},
                    {"timestamp": "NaN", "confidence": 0.9, "reason": "bad"},
                    {"timestamp": 20, "confidence": "bad", "reason": "bad"},
                ]
            }
        )
        suggestions = _parse_boundary_response(content)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].timestamp, 10)
        self.assertEqual(suggestions[0].confidence, 1.0)

    def test_prefers_capable_balanced_model(self):
        models = [
            {
                "name": "qwen3:27b",
                "details": {"parameter_size": "27.0B"},
                "capabilities": ["completion"],
            },
            {
                "name": "qwen3:9b",
                "details": {"parameter_size": "9.0B"},
                "capabilities": ["completion"],
            },
            {
                "name": "embed:latest",
                "details": {"parameter_size": "1.0B"},
                "capabilities": ["embedding"],
            },
        ]
        self.assertEqual(choose_model(models), "qwen3:9b")

    def test_falls_back_when_capabilities_are_absent(self):
        self.assertEqual(
            choose_model([{"name": "mistral:latest", "details": {}}]), "mistral:latest"
        )

    def test_description_timestamps_are_included_in_reasoning_prompt(self):
        reasoner = OllamaBoundaryReasoner()
        requests = []

        def request(path, payload=None):
            requests.append((path, payload))
            if path == "/api/tags":
                return {"models": [{"name": "qwen:8b", "details": {"parameter_size": "8B"}}]}
            return {"message": {"content": '{"boundaries": []}'}}

        reasoner._request = request
        reasoner.suggest_boundaries(
            [TranscriptSegment(0, 5, "Intro")],
            [],
            [],
            (VideoTimestamp(90, "Camera setup"),),
        )
        prompt = requests[-1][1]["messages"][1]["content"]
        self.assertIn("Camera setup", prompt)
        self.assertIn("90", prompt)
        self.assertNotIn("Visual scene changes", prompt)

    def test_complete_creator_chapters_are_marked_authoritative(self):
        reasoner = OllamaBoundaryReasoner()
        requests = []

        def request(path, payload=None):
            requests.append((path, payload))
            if path == "/api/tags":
                return {"models": [{"name": "qwen:8b", "details": {"parameter_size": "8B"}}]}
            return {"message": {"content": '{"boundaries": []}'}}

        reasoner._request = request
        reasoner.suggest_boundaries(
            [TranscriptSegment(0, 5, "Intro")],
            [1, 2, 3, 4, 5],
            [],
            (VideoTimestamp(0, "Story one", 0.95), VideoTimestamp(60, "Story two", 0.95)),
        )
        prompt = requests[-1][1]["messages"][1]["content"]
        self.assertIn("authoritative topic map", prompt)
        self.assertNotIn("[1, 2, 3, 4, 5]", prompt)


if __name__ == "__main__":
    unittest.main()
