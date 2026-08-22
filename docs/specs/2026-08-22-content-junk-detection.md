# Content Junk Detection Spec

ClipAuto must remove clearly non-editorial topic sections after natural topic detection and before splitting or duration grouping.

Sponsor-only topics are removed wherever they occur. Sponsor signals include titles beginning with sponsor, sponsored, advertisement, ad read, ad break, commercial break, paid promotion, partner message, “a word from our sponsor,” “this video is sponsored by,” or the chapter-style phrase “to Sponsor.” A title containing both sponsor language and one or more real topics joined with ` + ` is mixed content and must be preserved.

At the leading edge, exact generic titles Intro, Introduction, Opening, Video Intro, or Channel Intro are removed regardless of duration. At the trailing edge, exact generic titles Outro, Conclusion, Ending, Closing, Thanks for watching, End screen, Subscribe, or Call to action are removed regardless of duration. A descriptive leading title beginning with “Introduction to” is removed only when its source duration is at most 10 seconds; longer descriptive introductions remain content. Part suffixes such as `(Part 1/3)` do not prevent classification.

Removing internal junk creates separate contiguous content runs. Splitting and short-topic grouping operate independently within each run and must never produce a clip whose time range crosses a removed sponsor, intro, or outro interval. If no editorial content remains, planning fails clearly instead of rendering junk.
