import type { Components } from "react-markdown";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

interface ChatMarkdownProps {
  text: string;
}

// The model replies in markdown, but the bubble is a chat bubble, not a
// document: every block below is bent to the app's semantic tokens and
// compact spacing. The typography plugin is deliberately not used — its
// prose colors would fight the light/dark token theme, so the elements
// are styled by hand instead. react-markdown renders into React
// elements, never raw innerHTML, so nothing from the reply reaches the
// DOM as markup the app didn't map here.
const components: Components = {
  // Tailwind's preflight flattens headings, so the weight alone is the
  // hierarchy — chat-sized, never the giant document defaults.
  h1: ({ node, ...props }) => <h1 className="text-base font-semibold" {...props} />,
  h2: ({ node, ...props }) => <h2 className="font-semibold" {...props} />,
  h3: ({ node, ...props }) => <h3 className="font-semibold" {...props} />,
  h4: ({ node, ...props }) => <h4 className="font-medium" {...props} />,
  h5: ({ node, ...props }) => <h5 className="font-medium" {...props} />,
  h6: ({ node, ...props }) => <h6 className="font-medium" {...props} />,
  // Preflight strips list styling too: markers and indent come back
  // explicitly, with a hair of air between tight items.
  ul: ({ node, ...props }) => <ul className="list-disc pl-5 [&>li]:mt-0.5" {...props} />,
  ol: ({ node, ...props }) => <ol className="list-decimal pl-5 [&>li]:mt-0.5" {...props} />,
  blockquote: ({ node, ...props }) => (
    <blockquote className="border-l-2 border-border pl-3 text-text-secondary" {...props} />
  ),
  // react-markdown sanitizes URLs itself (javascript: and friends never
  // survive defaultUrlTransform); the blank target and rel are the last
  // mile — the site is a SPA and must not navigate inside its own tab.
  a: ({ node, ...props }) => (
    <a
      className="text-series-1 underline underline-offset-2 break-words"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  // One override for both code shapes: inline snippets get the wash and
  // the mono shrink; fenced blocks are the pre below, whose descendant
  // selectors strip this wash back off the code inside it. cn() keeps
  // the classes when react-markdown passes its own className for a
  // fenced block's language — a plain spread would silently drop them.
  code: ({ node, className, ...props }) => (
    <code
      className={cn("rounded bg-surface-2 px-1 py-0.5 font-mono text-xs", className)}
      {...props}
    />
  ),
  pre: ({ node, ...props }) => (
    <pre
      className="overflow-x-auto rounded-lg bg-surface-2 p-2.5 font-mono text-xs leading-relaxed [&_code]:rounded-none [&_code]:bg-transparent [&_code]:p-0"
      {...props}
    />
  ),
  // A wide table must scroll inside the bubble, not stretch it — hence
  // the wrapper div; it is also what the top-level spacing selector in
  // ChatMarkdown sees, so the rhythm stays uniform.
  table: ({ node, ...props }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs" {...props} />
    </div>
  ),
  th: ({ node, ...props }) => (
    <th className="border-b border-border py-1 pr-2 font-medium text-text-secondary" {...props} />
  ),
  td: ({ node, ...props }) => <td className="border-b border-border py-1 pr-2" {...props} />,
  hr: ({ node, ...props }) => <hr className="border-border" {...props} />,
  // A model-thrown image must fit the bubble, not stretch it — the
  // only markdown element that can break the mobile layout on its own.
  img: ({ node, ...props }) => <img className="h-auto max-w-full rounded-lg" {...props} />,
};

export function ChatMarkdown({ text }: ChatMarkdownProps) {
  return (
    // The wrapper owns the block rhythm: react-markdown emits bare
    // siblings, and this selector gives every block after the first an
    // even gap — lists and tables space themselves inside it.
    <div className="[&>*:not(:first-child)]:mt-2">
      {/* remark-breaks keeps the chat contract for plain-text replies:
          the old bubble preserved single newlines, and canonical
          markdown would fold them into one line — the plugin turns soft
          breaks into <br> instead, so both dialects read as typed. */}
      <Markdown remarkPlugins={[remarkGfm, remarkBreaks]} components={components}>
        {text}
      </Markdown>
    </div>
  );
}
