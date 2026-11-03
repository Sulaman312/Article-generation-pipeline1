import { useMemo } from "react";
import { parseBrief } from "../../utils/parseBrief";
import KeyValueStructured from "./KeyValueStructured";

export default function BriefStructured({ text }) {
  const fields = useMemo(() => parseBrief(text), [text]);
  if (!fields?.length) return null;
  return <KeyValueStructured fields={fields} className="brief-structured" />;
}
