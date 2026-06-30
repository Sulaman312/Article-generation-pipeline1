/** Must stay in sync with `backend/pipeline.py` STEP_ORDER. */
export const PIPELINE_STEPS = [
  {
    key: "topic_card",
    label: "Topic Card",
    matrixLabel: "Plan & topic",
    matrixCol: "TC",
    index: 1,
  },
  {
    key: "serp_research",
    label: "SERP Research",
    matrixLabel: "Search landscape",
    matrixCol: "SR",
    index: 2,
  },
  {
    key: "research",
    label: "SERP Analysis & Gaps",
    matrixLabel: "Gap analysis",
    matrixCol: "SA",
    index: 3,
  },
  {
    key: "assignment_brief",
    label: "Assignment Brief",
    matrixLabel: "Editorial brief",
    matrixCol: "BR",
    index: 4,
  },
  {
    key: "outline",
    label: "Outline",
    matrixLabel: "Article outline",
    matrixCol: "OL",
    index: 5,
  },
  {
    key: "draft",
    label: "Draft",
    matrixLabel: "First draft",
    matrixCol: "DR",
    index: 6,
  },
  {
    key: "fact_check",
    label: "Fact Check (web + editor)",
    matrixLabel: "Review & accuracy",
    matrixCol: "FC",
    index: 7,
  },
  {
    key: "final_output",
    label: "Final Output",
    matrixLabel: "Ready to publish",
    matrixCol: "FO",
    index: 8,
  },
];

export const PIPELINE_STEP_KEYS = PIPELINE_STEPS.map((s) => s.key);
