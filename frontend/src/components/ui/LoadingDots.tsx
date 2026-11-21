import { cn } from "@/lib/utils";

// Three slowly blinking dots — a wordless "the other side is working"
// indicator. Purely presentational: semantics live on whatever wraps
// it (the assistant page hangs role="status" plus an aria-label there),
// the dots themselves stay aria-hidden so screen readers hear words,
// not three silent spans. Each dot's phase is shifted by a plain
// animation-delay; motion-reduce parks the dots at rest for users who
// asked the OS not to animate.
export function LoadingDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1", className)} aria-hidden="true">
      <span className="size-1.5 rounded-full bg-text-secondary animate-typing-dot motion-reduce:animate-none" />
      <span className="size-1.5 rounded-full bg-text-secondary animate-typing-dot [animation-delay:150ms] motion-reduce:animate-none" />
      <span className="size-1.5 rounded-full bg-text-secondary animate-typing-dot [animation-delay:300ms] motion-reduce:animate-none" />
    </span>
  );
}
