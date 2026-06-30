/**
 * Single-app vs split deployments.
 * Set REACT_APP_PROJECT_MODE=article | social (omit or "all" for both pipelines).
 */
const MODE = (process.env.REACT_APP_PROJECT_MODE || "all").trim().toLowerCase();

export const APP_PROJECT_MODE = MODE;

export function isSingleProjectMode() {
  return MODE === "article" || MODE === "social";
}

/** When set, the UI only exposes one pipeline ("content" | "social"). */
export function lockedActivePipeline() {
  if (MODE === "article") return "content";
  if (MODE === "social") return "social";
  return null;
}

export function appProductMeta() {
  if (MODE === "article") {
    return {
      name: "Article Pipeline",
      workspaceTagline: "Editorial Workspace",
    };
  }
  if (MODE === "social") {
    return {
      name: "Post Generation Pipeline",
      workspaceTagline: "Social Workspace",
    };
  }
  return {
    name: "ContentFlow",
    workspaceTagline: "Editorial Workspace",
  };
}
