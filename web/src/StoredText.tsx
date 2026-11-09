import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Reading transformations never change the saved body. HTML and remote images
// are deliberately not executed; local historical links are not remapped.
export function StoredText({ body, format = "plain_text" }: { body: string; format?: string | null }) {
  const [renderLarge, setRenderLarge] = useState(false);
  const markdown = ["markdown", "text/markdown", "slack"].includes((format ?? "").split(";")[0].trim().toLowerCase());
  if (markdown && body.length > 1_000_000 && !renderLarge) return <div className="stored-text">
    <p className="muted">Large document · {body.length.toLocaleString()} characters. Rendering the full document may take a moment.</p>
    <button onClick={() => setRenderLarge(true)}>Render full document</button>
  </div>;
  if (!markdown) return <pre className="source-text-preview stored-text">{body}</pre>;
  const display = format === "slack" ? body.replace(/<(https?:\/\/[^<>|\s]+)(?:\|([^<>]*))?>/g, (_match, url: string, label?: string) =>
    `[${(label || url).replace(/[\\[\]]/g, "\\$&")}](${url.replace(/[()]/g, c => `%${c.charCodeAt(0).toString(16)}`)})`) : body;
  return <div className="artifact-markdown stored-text"><Markdown skipHtml remarkPlugins={[remarkGfm]} components={{
    img: ({ alt }) => <span>[External image: {alt || "not loaded"}]</span>,
    a: ({ href, children }) => {
      if (!href || !/^https?:\/\//i.test(href)) return <span>{children} <small className="muted">(original link unavailable)</small></span>;
      let original = false;
      try { original = /^(localhost|127\.|\[::1\])/.test(new URL(href).hostname); } catch { return <span>{children}</span>; }
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}{original && <small> (original local link)</small>}</a>;
    },
  }}>{display}</Markdown></div>;
}
