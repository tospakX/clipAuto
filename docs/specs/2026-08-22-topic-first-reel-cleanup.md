# Topic-First Reel Cleanup Spec

ClipAuto must preserve the natural topic division produced by description chapters or Ollama. Duration is a cleanup preference, not the primary segmentation rule.

The workflow is ordered:

1. Detect and normalize natural topic boundaries.
2. Remove sponsor-only topics anywhere, preserving titles that combine sponsor and editorial content.
3. Remove exact generic intros at the leading edge and exact generic outros at the trailing edge. Remove descriptive edge sections only when they are 10 seconds or shorter.
4. Split retained content into independent contiguous runs so no output can cross a removed interval.
5. Split an individually oversized topic only when it can become multiple full reels. Prefer transcript segment boundaries, then word boundaries, with balanced time cuts only as a final fallback.
6. Merge adjacent undersized useful topics within each run toward the 44–66 source-second preference. Preserve already suitable natural topics, and accept an unavoidable shorter or longer result rather than repartitioning the whole video across semantic boundaries.

A short but meaningful topic must be merged rather than discarded. A source consisting of one meaningful short topic remains one clip. A substantial descriptive title such as “Introduction to living on other planets” remains content; an exact edge title such as “Intro” or “Outro” is treated as non-editorial.

Rendering, validation, and atomic publication continue to follow the zero-broken-reels media contract.
