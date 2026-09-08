import pytest

from clipauto.models import Topic, TranscriptSegment, TranscriptWord
from clipauto.topics import (
    TopicValidationError,
    combine_topics_for_output,
    extract_json_array,
    normalize_topics,
    partition_topic_groups,
    plan_reel_topics,
    split_oversized_topics,
    topics_from_chapters,
    topics_from_transcript,
)

SEGMENTS = [
    TranscriptSegment(0.0, 8.0, "Opening sentence."),
    TranscriptSegment(8.0, 20.0, "The first subject ends here."),
    TranscriptSegment(20.0, 32.0, "A new subject starts."),
    TranscriptSegment(32.0, 45.0, "It finishes cleanly."),
]


def test_extracts_json_array_from_fenced_model_response():
    value = extract_json_array('Result:\n```json\n[{"title":"A","start":0,"end":5}]\n```')
    assert value == [{"title": "A", "start": 0, "end": 5}]


def test_extracts_first_valid_topic_array_after_model_reasoning_noise():
    value = extract_json_array(
        '<think>[not valid JSON]</think>\n'
        '[{"title":"Useful answer","start":0,"end":45}]\nDone.'
    )

    assert value == [{"title": "Useful answer", "start": 0, "end": 45}]


def test_normalizes_gaps_and_overlap_to_sentence_boundary():
    raw = [
        {"title": "First subject", "start": 1, "end": 18},
        {"title": "Second subject", "start": 22, "end": 49},
    ]

    topics = normalize_topics(raw, SEGMENTS, duration=45.0)

    assert [(topic.start, topic.end) for topic in topics] == [(0.0, 20.0), (20.0, 45.0)]


def test_single_topic_covers_entire_video_without_duration_cap():
    topics = normalize_topics(
        [{"title": "Long discussion", "start": 7, "end": 180}], SEGMENTS, duration=240.0
    )
    assert [(topic.start, topic.end) for topic in topics] == [(0.0, 240.0)]


def test_normalization_discards_duplicate_model_ranges_and_keeps_useful_topics():
    topics = normalize_topics(
        [
            {"title": "First", "start": 0, "end": 10},
            {"title": "Duplicate", "start": 0, "end": 10},
            {"title": "Second", "start": 20, "end": 30},
        ],
        [
            TranscriptSegment(0, 10, "First subject."),
            TranscriptSegment(10, 20, "Transition."),
            TranscriptSegment(20, 30, "Second subject."),
        ],
        duration=30,
    )

    assert topics == [Topic("First", 0, 10), Topic("Second", 10, 30)]


def test_transcript_fallback_is_readable_contiguous_and_deterministic():
    segments = [
        TranscriptSegment(0, 28, "Why sleep quality matters for memory."),
        TranscriptSegment(28, 55, "A practical evening routine improves sleep."),
        TranscriptSegment(55, 82, "Morning light helps the body clock."),
        TranscriptSegment(82, 110, "Consistency matters more than perfection."),
    ]

    topics = topics_from_transcript(segments, duration=110)

    assert topics == [
        Topic("Why sleep quality matters for memory", 0, 55),
        Topic("Morning light helps the body clock", 55, 110),
    ]


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [{"title": "", "start": 0, "end": 5}],
        [{"title": "Broken", "start": "now", "end": 5}],
        [{"title": "Backwards", "start": 8, "end": 2}],
    ],
)
def test_rejects_malformed_topic_output(raw):
    with pytest.raises(TopicValidationError):
        normalize_topics(raw, SEGMENTS, duration=45.0)


def test_rejects_non_json_model_text():
    with pytest.raises(TopicValidationError, match="JSON array"):
        extract_json_array("Here are the best moments: none")


def test_description_chapter_starts_become_exact_contiguous_boundaries():
    chapters = [
        {"title": "Opening", "start_time": 0, "end_time": 28},
        {"title": "Caffeine", "start_time": 30, "end_time": 66},
        {"title": "Sleep", "start_time": 66, "end_time": 92},
    ]

    topics = topics_from_chapters(chapters, duration=92)

    assert [(topic.title, topic.start, topic.end) for topic in topics] == [
        ("Opening", 0.0, 30.0),
        ("Caffeine", 30.0, 66.0),
        ("Sleep", 66.0, 92.0),
    ]


def test_description_chapters_cover_leading_and_trailing_video_time():
    chapters = [
        {"title": "First named section", "start_time": 3, "end_time": 20},
        {"title": "Last section", "start_time": 20, "end_time": 38},
    ]

    topics = topics_from_chapters(chapters, duration=40)

    assert [(topic.start, topic.end) for topic in topics] == [(0.0, 20.0), (20.0, 40.0)]


@pytest.mark.parametrize(
    "chapters",
    [
        [],
        [{"title": "", "start_time": 0}],
        [{"title": "Bad", "start_time": "soon"}],
        [
            {"title": "One", "start_time": 0},
            {"title": "Duplicate", "start_time": 0},
        ],
        [
            {"title": "Later", "start_time": 20},
            {"title": "Earlier", "start_time": 10},
        ],
        [{"title": "Beyond video", "start_time": 100}],
    ],
)
def test_malformed_description_chapters_fall_back_to_topic_detection(chapters):
    assert topics_from_chapters(chapters, duration=40) is None


def test_combines_two_or_three_short_topics_into_40_to_60_second_outputs():
    topics = [
        Topic("One", 0, 15),
        Topic("Two", 15, 30),
        Topic("Three", 30, 45),
        Topic("Complete topic", 45, 95),
        Topic("Four", 95, 115),
        Topic("Five", 115, 135),
        Topic("Six", 135, 155),
    ]

    combined = combine_topics_for_output(topics)

    assert [(topic.title, topic.start, topic.end) for topic in combined] == [
        ("One + Two + Three", 0, 45),
        ("Complete topic", 45, 95),
        ("Four + Five + Six", 95, 155),
    ]


def test_fuses_as_many_tiny_topics_as_needed_to_reach_output_range():
    topics = [Topic(str(index), index * 10, (index + 1) * 10) for index in range(8)]

    groups = partition_topic_groups(topics)

    assert [[topic.title for topic in group] for group in groups] == [
        ["0", "1", "2", "3"],
        ["4", "5", "6", "7"],
    ]


def test_fuses_short_remainder_with_adjacent_target_length_topic():
    topics = [Topic("Forty four", 0, 44), Topic("Seventeen", 44, 61)]

    assert combine_topics_for_output(topics) == [Topic("Forty four + Seventeen", 0, 61)]


def test_fuses_ten_second_topic_with_adjacent_fifty_second_topic():
    topics = [Topic("Main topic", 0, 50), Topic("Short ending", 50, 60)]

    assert combine_topics_for_output(topics) == [Topic("Main topic + Short ending", 0, 60)]


def test_prefers_three_topic_fifty_second_group_over_short_pair():
    topics = [
        Topic("One", 0, 12),
        Topic("Two", 12, 29),
        Topic("Three", 29, 50),
        Topic("Four", 50, 70),
        Topic("Five", 70, 90),
    ]

    assert combine_topics_for_output(topics) == [
        Topic("One + Two + Three", 0, 50),
        Topic("Four + Five", 50, 90),
    ]


def test_does_not_join_two_almost_target_length_topics_into_oversized_output():
    topics = [Topic("One", 0, 44), Topic("Two", 44, 88)]

    assert combine_topics_for_output(topics) == topics


def test_splits_oversized_topic_into_balanced_parts_at_transcript_boundaries():
    topics = [Topic("Long discussion", 0, 240)]
    segments = [
        TranscriptSegment(start, start + 30, f"Sentence {index}.")
        for index, start in enumerate(range(0, 240, 30))
    ]

    split = split_oversized_topics(topics, segments, minimum=40, maximum=60)

    assert [(topic.title, topic.start, topic.end) for topic in split] == [
        ("Long discussion (Part 1/4)", 0, 60),
        ("Long discussion (Part 2/4)", 60, 120),
        ("Long discussion (Part 3/4)", 120, 180),
        ("Long discussion (Part 4/4)", 180, 240),
    ]


def test_keeps_topic_at_maximum_duration_unchanged():
    topic = Topic("Complete thought", 0, 60)

    assert split_oversized_topics([topic], SEGMENTS, maximum=60) == [topic]


def test_uses_earlier_sentence_boundary_instead_of_exceeding_maximum():
    boundaries = [0, 56, 112.5, 117, 172, 230]
    segments = [
        TranscriptSegment(start, end, f"Sentence {index}.")
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:], strict=False))
    ]

    split = split_oversized_topics(
        [Topic("Long discussion", 0, 230)], segments, minimum=40, maximum=60
    )

    assert [(topic.start, topic.end) for topic in split] == [
        (0, 56),
        (56, 112.5),
        (112.5, 172),
        (172, 230),
    ]


def test_reel_plan_fuses_forty_second_topic_and_twenty_second_remainder():
    planned = plan_reel_topics(
        [Topic("Main", 0, 40), Topic("Final detail", 40, 60)],
        [TranscriptSegment(0, 40, "Main."), TranscriptSegment(40, 60, "Detail.")],
    )

    assert planned == [Topic("Main + Final detail", 0, 60)]


def test_reel_plan_preserves_two_natural_near_target_topics():
    planned = plan_reel_topics(
        [Topic("First", 0, 40), Topic("Second", 40, 80)],
        [TranscriptSegment(0, 40, "First."), TranscriptSegment(40, 80, "Second.")],
    )

    assert planned == [Topic("First", 0, 40), Topic("Second", 40, 80)]


def test_reel_plan_splits_long_topic_into_balanced_contiguous_reels():
    planned = plan_reel_topics(
        [Topic("Long subject", 0, 120)],
        [
            TranscriptSegment(0, 30, "One."),
            TranscriptSegment(30, 60, "Two."),
            TranscriptSegment(60, 90, "Three."),
            TranscriptSegment(90, 120, "Four."),
        ],
    )

    assert planned == [
        Topic("Long subject (Part 1/2)", 0, 60),
        Topic("Long subject (Part 2/2)", 60, 120),
    ]


@pytest.mark.parametrize(
    "topics, expected",
    [
        (
            [Topic("Introduction", 0, 2), Topic("Main subject", 2, 60)],
            [Topic("Main subject", 2, 60)],
        ),
        (
            [Topic("Main subject", 0, 58), Topic("Outro", 58, 60)],
            [Topic("Main subject", 0, 58)],
        ),
    ],
)
def test_reel_plan_removes_micro_intro_or_outro(topics, expected):
    planned = plan_reel_topics(topics, [TranscriptSegment(0, 60, "Complete reel.")])

    assert planned == expected


def test_reel_plan_keeps_lone_meaningful_short_source():
    planned = plan_reel_topics(
        [Topic("Concise useful topic", 0, 20)],
        [TranscriptSegment(0, 20, "A complete concise explanation.")],
    )

    assert planned == [Topic("Concise useful topic", 0, 20)]


def test_reel_plan_keeps_substantial_descriptive_introduction():
    planned = plan_reel_topics(
        [
            Topic("Introduction to living on other planets", 0, 36),
            Topic("Life on Mars", 36, 86),
        ],
        [
            TranscriptSegment(0, 36, "A substantial introductory lesson."),
            TranscriptSegment(36, 86, "The main lesson."),
        ],
    )

    assert planned == [
        Topic("Introduction to living on other planets", 0, 36),
        Topic("Life on Mars", 36, 86),
    ]


@pytest.mark.parametrize(
    "topics, expected",
    [
        (
            [Topic("Intro", 0, 60), Topic("Main subject", 60, 110)],
            [Topic("Main subject", 60, 110)],
        ),
        (
            [Topic("Main subject", 0, 50), Topic("Outro (Part 1/3)", 50, 110)],
            [Topic("Main subject", 0, 50)],
        ),
        (
            [
                Topic("Introduction to weird lawsuits", 0, 10),
                Topic("First lawsuit", 10, 60),
            ],
            [Topic("First lawsuit", 10, 60)],
        ),
    ],
)
def test_reel_plan_removes_detected_edge_sections_regardless_of_old_threshold_bug(
    topics, expected
):
    segments = [TranscriptSegment(topic.start, topic.end, topic.title) for topic in topics]

    assert plan_reel_topics(topics, segments) == expected


@pytest.mark.parametrize(
    "sponsor_title",
    [
        "to Sponsor (Ground News)",
        "to Sponsor Segment (Abacus AI)",
        "Sponsored message",
        "Advertisement",
        "Ad Break",
        "Ad read",
        "Commercial break",
        "Paid promotion",
        "A word from our sponsor",
        "This video is sponsored by Acme",
        "Partner Message (Part 1/2)",
    ],
)
def test_reel_plan_removes_internal_sponsor_without_spanning_its_gap(sponsor_title):
    topics = [
        Topic("First subject", 0, 50),
        Topic(sponsor_title, 50, 110),
        Topic("Second subject", 110, 160),
    ]

    planned = plan_reel_topics(
        topics,
        [TranscriptSegment(topic.start, topic.end, topic.title) for topic in topics],
    )

    assert planned == [
        Topic("First subject", 0, 50),
        Topic("Second subject", 110, 160),
    ]


@pytest.mark.parametrize(
    "edge_title",
    [
        "Video Intro",
        "Channel Intro",
        "Thanks for watching",
        "End screen",
        "Subscribe",
        "Call to action",
    ],
)
def test_reel_plan_removes_common_non_editorial_edge_labels(edge_title):
    leading = "intro" in edge_title.casefold()
    topics = (
        [Topic(edge_title, 0, 30), Topic("Main subject", 30, 80)]
        if leading
        else [Topic("Main subject", 0, 50), Topic(edge_title, 50, 80)]
    )

    planned = plan_reel_topics(
        topics,
        [TranscriptSegment(topic.start, topic.end, topic.title) for topic in topics],
    )

    expected = Topic("Main subject", 30, 80) if leading else Topic("Main subject", 0, 50)
    assert planned == [expected]


def test_reel_plan_preserves_mixed_sponsor_and_editorial_topic():
    mixed = Topic("to Sponsor (Incogni) + Keyhole Cave (Part 1/3)", 0, 60)

    assert plan_reel_topics([mixed], [TranscriptSegment(0, 60, "Mixed content")]) == [
        mixed
    ]


def test_reel_plan_rejects_source_containing_only_junk_sections():
    with pytest.raises(TopicValidationError, match="no editorial content"):
        plan_reel_topics(
            [Topic("Intro", 0, 30), Topic("to Sponsor (Odoo)", 30, 90)],
            [TranscriptSegment(0, 30, "Intro"), TranscriptSegment(30, 90, "Ad")],
        )


def test_reel_plan_falls_back_to_balanced_cut_for_unbroken_transcript():
    planned = plan_reel_topics(
        [Topic("Unbroken monologue", 0, 120)],
        [TranscriptSegment(0, 120, "One unbroken segment.")],
    )

    assert planned == [
        Topic("Unbroken monologue (Part 1/2)", 0, 60),
        Topic("Unbroken monologue (Part 2/2)", 60, 120),
    ]


def test_reel_plan_uses_word_boundaries_when_segment_edges_cannot_form_full_reels():
    planned = plan_reel_topics(
        [Topic("Long monologue", 0, 125)],
        [
            TranscriptSegment(
                0,
                125,
                "A single coarse transcript segment.",
                words=[
                    TranscriptWord(0, 60, "First thought."),
                    TranscriptWord(60, 65, "Transition."),
                    TranscriptWord(65, 125, "Second thought."),
                ],
            )
        ],
    )

    assert planned == [
        Topic("Long monologue (Part 1/2)", 0, 60),
        Topic("Long monologue (Part 2/2)", 60, 125),
    ]


def test_reel_plan_keeps_natural_topics_then_filters_and_combines():
    topics = [
        Topic("Introduction", 0, 2),
        Topic("First complete subject", 2, 52),
        Topic("Brief useful detail", 52, 64),
        Topic("Second complete subject", 64, 114),
        Topic("Outro", 114, 117),
    ]

    planned = plan_reel_topics(
        topics,
        [TranscriptSegment(topic.start, topic.end, topic.title) for topic in topics],
    )

    assert planned == [
        Topic("First complete subject", 2, 52),
        Topic("Brief useful detail + Second complete subject", 52, 114),
    ]


@pytest.mark.parametrize(
    "source_duration",
    [
        44,
        60,
        66,
        67,
        80,
        87,
        88,
        89,
        100,
        120,
        131,
        132,
        133,
        175,
        176,
        177,
        239,
        240,
        241,
        599,
        600,
    ],
)
def test_reel_plan_duration_invariants_across_dense_sources(source_duration):
    segments = [
        TranscriptSegment(start, min(start + 1, source_duration), "Sentence.")
        for start in range(source_duration)
    ]
    planned = plan_reel_topics(
        [Topic("Subject", 0, source_duration)],
        segments,
    )

    assert planned[0].start == 0
    assert planned[-1].end == source_duration
    assert all(topic.end - topic.start >= 44 for topic in planned)
    assert all(
        left.end == right.start
        for left, right in zip(planned, planned[1:], strict=False)
    )
    if len(planned) > 1:
        assert all(topic.end - topic.start <= 66 for topic in planned)
