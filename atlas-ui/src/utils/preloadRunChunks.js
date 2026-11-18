/**
 * Warm markdown/editor chunks when the user opens a run so ArtifactView
 * does not hitch on first step switch.
 */
let preloading = false;

export function preloadRunChunks() {
  if (preloading || typeof window === "undefined") return;
  preloading = true;
  // Fire-and-forget; webpack/CRA turns these into separate async chunks.
  Promise.all([
    import("../components/run/RunView"),
    import("../components/run/FinalOutputDocEditor"),
    import("../components/run/FinalOutputMetadataPanel"),
    import("../components/shared/MarkdownArtifactPanel"),
    import("../components/shared/Markdown"),
    import("../components/run/TopicCardStructured"),
    import("../components/run/MetaSeoStructured"),
    import("../components/run/FactCheckStructured"),
    import("../components/run/BriefStructured"),
    import("../components/run/ResearchStructured"),
    import("../components/run/SerpResearchStructured"),
    import("../components/run/OutlineStructured"),
    import("../components/run/DraftStructured"),
    import("../components/run/ArtifactFormattedPreview"),
  ]).catch(() => {
    /* ignore — next real import will retry */
  });
}
