import unittest

from youtube_clipper.naming import safe_component, video_directory_name


class SafeNamingTests(unittest.TestCase):
    def test_removes_cross_platform_unsafe_characters_and_reserved_names(self):
        self.assertEqual(safe_component('  CON: a/b?*  ', "video"), "con-a-b")
        self.assertEqual(safe_component('AUX', "video"), "video")
        self.assertEqual(safe_component('CON.txt', "video"), "video")
        self.assertEqual(safe_component('...   ', "video"), "video")

    def test_video_directory_uses_id_to_separate_similar_titles(self):
        first = video_directory_name("My Great Video", "abc123")
        second = video_directory_name("My Great Video", "xyz789")

        self.assertEqual(first, "my-great-video-abc123")
        self.assertEqual(second, "my-great-video-xyz789")
        self.assertNotEqual(first, second)

    def test_names_are_bounded_without_dropping_unique_id(self):
        result = video_directory_name("word " * 100, "abc123")

        self.assertLessEqual(len(result), 96)
        self.assertTrue(result.endswith("-abc123"))


if __name__ == "__main__":
    unittest.main()
