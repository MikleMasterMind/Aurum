import { useEffect, useRef, useState } from "react";
import { RefreshCw, Send } from "lucide-react";
import { ApiError } from "@/api/client";
import { confirmChatCalls, resetChatThread, sendChatMessage } from "@/api/chat";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useChatStatus } from "@/hooks/useChatStatus";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { ChatPendingCall, ChatTurn } from "@/types";

// The conversation key, kept in localStorage. The server-side thread
// lives in the backend's process memory: after a backend restart the id
// survives but the model starts over — a late confirmation then
// honestly answers confirm_expired instead of writing anything.
const THREAD_KEY = "aurum:chat-thread";

// The page's own view of the conversation — the log, the pending
// confirmation cards, the per-card decisions. The router unmounts this
// page on every tab switch and useState dies with it, while the
// server-side thread lives on: without restoring the view, the user
// comes back to an empty screen and a model that still remembers
// everything. One entry for all three, written on change, read lazily
// on mount.
const VIEW_KEY = "aurum:chat-view";

// The log is a display cache, not a diary: localStorage must not grow
// unbounded with a long conversation, so writes trim to the newest
// messages.
const LOG_CAP = 100;

interface PersistedChatView {
  messages: UiMessage[];
  pending: ChatPendingCall[] | null;
  decided: Record<string, boolean>;
}

function loadPersistedView(): PersistedChatView {
  // A missing or corrupted entry starts clean — never worth crashing
  // the page over a display cache. Shapes are checked, not trusted,
  // down to the entries themselves: the renderer assumes text is a
  // string and args is an object, and a hand-tampered or foreign-
  // version entry must degrade, not crash render.
  try {
    const raw = localStorage.getItem(VIEW_KEY);
    if (!raw) return { messages: [], pending: null, decided: {} };
    const parsed = JSON.parse(raw) as Partial<PersistedChatView>;
    const messages = (Array.isArray(parsed.messages) ? parsed.messages : []).filter(
      (message) =>
        message &&
        typeof message.text === "string" &&
        (message.role === "user" || message.role === "assistant")
    );
    const pending = (Array.isArray(parsed.pending) ? parsed.pending : []).filter(
      (call) =>
        call &&
        typeof call.id === "string" &&
        typeof call.name === "string" &&
        typeof call.args === "object" &&
        call.args !== null &&
        // names is optional (an entry from before the resolution, or a
        // write with nothing to resolve) but when present it must be a
        // string map — the renderer interpolates its values as-is.
        (call.names === undefined ||
          call.names === null ||
          (typeof call.names === "object" &&
            !Array.isArray(call.names) &&
            Object.values(call.names).every((value) => typeof value === "string")))
    );
    const decided =
      parsed.decided && typeof parsed.decided === "object" && !Array.isArray(parsed.decided)
        ? Object.fromEntries(
            Object.entries(parsed.decided).filter(([, value]) => typeof value === "boolean")
          )
        : {};
    return { messages, pending: pending.length > 0 ? pending : null, decided };
  } catch {
    return { messages: [], pending: null, decided: {} };
  }
}

// Error codes from the backend (services/agent_chat.py) mapped to
// localized text: codes, not messages, travel the API so the page can
// speak either language; the fallback keeps a future unknown code from
// rendering as a blank bubble.
const ERROR_KEYS: Record<string, TranslationKey> = {
  turn_failed: "assistant.error.turnFailed",
  confirm_required: "assistant.error.confirmRequired",
  confirm_expired: "assistant.error.confirmExpired",
};

// Labels for the agent's write tools (the same registry the terminal
// preview uses, see agent/aurum_agent/repl.py). An unknown tool name
// falls back to the raw name — honest, and future tools stay legible.
const ACTION_KEYS: Record<string, TranslationKey> = {
  create_transaction: "assistant.action.createTransaction",
  update_transaction: "assistant.action.updateTransaction",
  delete_transaction: "assistant.action.deleteTransaction",
  create_account: "assistant.action.createAccount",
  update_account: "assistant.action.updateAccount",
  delete_account: "assistant.action.deleteAccount",
  create_category: "assistant.action.createCategory",
  update_category: "assistant.action.updateCategory",
  delete_category: "assistant.action.deleteCategory",
  create_tag: "assistant.action.createTag",
};

// Labels for the id arguments whose resolved names the payload may
// carry — the same key set as the terminal's ARG_LABELS (the resolver
// itself is aurum_agent/naming.py, the labels agent/aurum_agent/repl.py).
// The formatting is each frontend's own: the card pairs a localized
// label with the name, the terminal keeps its key=value dump shape.
// An unknown key falls back to the raw key — honest, and future id
// arguments stay legible.
const ARG_KEYS: Record<string, TranslationKey> = {
  account_id: "assistant.arg.account",
  transfer_account_id: "assistant.arg.transferAccount",
  category_id: "assistant.arg.category",
  parent_id: "assistant.arg.parentCategory",
  tag_ids: "assistant.arg.tags",
};

interface UiMessage {
  role: "user" | "assistant";
  text: string;
  isError?: boolean;
}

function actionLabel(name: string, t: ReturnType<typeof useTranslation>["t"]): string {
  const key = ACTION_KEYS[name];
  // The action stays a label; the honesty of the arguments lives in
  // formatArgs — ids turn into names only when the payload resolved
  // them, otherwise they show raw.
  return key ? t(key) : name;
}

// key=value pairs for the card body, mirroring the terminal's
// describe_call: one line, nothing hidden. The id arguments render as
// «Счёт: Карта» when the payload carries a resolved name; everything
// else — and any id that failed to resolve — stays raw.
function formatArgs(
  args: Record<string, unknown>,
  names: Record<string, string> | null | undefined,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  return Object.entries(args)
    .map(([key, value]) => {
      const name = names?.[key];
      if (name !== undefined) {
        const label = ARG_KEYS[key];
        return `${label ? t(label) : key}: ${name}`;
      }
      return `${key}=${JSON.stringify(value) ?? "null"}`;
    })
    .join(", ");
}

export function AssistantPage() {
  const { t } = useTranslation();
  const { data: status, isLoading, isError } = useChatStatus();

  const [threadId, setThreadId] = useState<string>(() => localStorage.getItem(THREAD_KEY) ?? "");
  // One logical parse per mount feeds all three states: in production
  // the lazy initializer runs once (dev's StrictMode double-invokes it
  // — one extra harmless read) — and the view returns as it was left,
  // modulo the LOG_CAP trim.
  const [restored] = useState(loadPersistedView);
  const [messages, setMessages] = useState<UiMessage[]>(restored.messages);
  const [pending, setPending] = useState<ChatPendingCall[] | null>(restored.pending);
  // Per-card decisions until the whole batch is answered — the backend
  // takes one boolean list, so the cards lock as they are clicked and
  // the request fires only once every card has its answer.
  const [decided, setDecided] = useState<Record<string, boolean>>(restored.decided);
  const [input, setInput] = useState("");
  // One turn at a time, end to end: locks the send button, the cards
  // and the new-chat button while a turn is running.
  const [busy, setBusy] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (threadId) localStorage.setItem(THREAD_KEY, threadId);
  }, [threadId]);

  // The view outlives the route: written on every change so returning
  // to the tab (or reloading) brings the log, the cards and the half-
  // answered decisions back. handleReset clears all three states, which
  // lands here as the empty snapshot — no special casing needed.
  useEffect(() => {
    localStorage.setItem(
      VIEW_KEY,
      JSON.stringify({
        messages: messages.slice(-LOG_CAP),
        pending,
        decided,
      })
    );
  }, [messages, pending, decided]);

  // Keep the newest turn in view — on mobile the log scrolls under the
  // keyboard otherwise, and the just-typed message must stay visible.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  // Turn outcomes, one path for message and confirm alike: an error
  // code becomes a localized bubble, a pending list becomes cards (and
  // locks the input), a reply becomes a bubble.
  const applyTurn = (turn: ChatTurn) => {
    if (turn.error) {
      const key = ERROR_KEYS[turn.error];
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: key ? t(key) : t("assistant.error.generic"), isError: true },
      ]);
      // confirm_required means the cards are still the question — they
      // stay; every other error implies nothing is pending anymore (the
      // service dropped the registry entry with the failed turn).
      if (turn.error !== "confirm_required") setPending(null);
      setDecided({});
      return;
    }
    if (turn.pending.length > 0) {
      setPending(turn.pending);
      setDecided({});
      return;
    }
    setPending(null);
    setDecided({});
    if (turn.reply) setMessages((prev) => [...prev, { role: "assistant", text: turn.reply }]);
  };

  const runTurn = async (action: () => Promise<ChatTurn>) => {
    setBusy(true);
    try {
      applyTurn(await action());
    } catch (error) {
      // The expected case is the unconfigured 400 (the key was removed
      // after the page loaded) — show the setup hint, not a raw backend
      // detail; anything else is a failed turn, same as the backend's
      // turn_failed code.
      const text =
        error instanceof ApiError && error.status === 400
          ? t("assistant.unconfigured.hint")
          : t("assistant.error.turnFailed");
      setMessages((prev) => [...prev, { role: "assistant", text, isError: true }]);
    } finally {
      setBusy(false);
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || busy || pending) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    // A first visit has no thread yet — mint one together with the
    // first message rather than on page load, so the status-only visit
    // costs nothing. busy is set for the mint too: a second send in
    // that window would mint a second thread otherwise.
    let thread = threadId;
    if (!thread) {
      setBusy(true);
      try {
        const { thread_id } = await resetChatThread(null);
        setThreadId(thread_id);
        thread = thread_id;
      } catch {
        // A network blip while minting: same recovery as a failed
        // turn — the message stays in the log, the user retries it.
        setBusy(false);
        setMessages((prev) => [
          ...prev,
          { role: "assistant", text: t("assistant.error.turnFailed"), isError: true },
        ]);
        return;
      }
    }
    await runTurn(() => sendChatMessage(thread, text));
  };

  const handleDecide = async (call: ChatPendingCall, approved: boolean) => {
    if (!pending || busy) return;
    const next = { ...decided, [call.id]: approved };
    if (Object.keys(next).length < pending.length) {
      // Batch partially answered — lock this card, keep collecting.
      setDecided(next);
      return;
    }
    // Last card decided: send the whole batch in the pending order.
    setDecided(next);
    await runTurn(() => confirmChatCalls(threadId, pending.map((item) => next[item.id] ?? false)));
  };

  const handleReset = async () => {
    if (busy) return;
    try {
      const { thread_id } = await resetChatThread(threadId || null);
      setThreadId(thread_id);
      setMessages([]);
      setPending(null);
      setDecided({});
    } catch {
      // A failed reset is not fatal — the conversation simply continues
      // in the old thread, so the error is swallowed on purpose.
    }
  };

  if (isLoading) {
    return <p className="py-10 text-center text-sm text-text-muted">{t("common.loading")}</p>;
  }

  // A failed status fetch is a transient outage, not "no key" — showing
  // the setup card here would send the user to fix a .env that is fine.
  if (isError) {
    return <p className="py-10 text-center text-sm text-text-muted">{t("assistant.error.generic")}</p>;
  }

  if (!status?.configured) {
    return (
      <div className="mx-auto w-full max-w-2xl">
        <Card>
          <CardHeader>
            <CardTitle>{t("assistant.unconfigured.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-text-secondary">{t("assistant.unconfigured.hint")}</p>
            <p className="mt-3 rounded-md bg-surface-2 px-3 py-2 font-mono text-xs text-text-primary">
              AURUM_AGENT_LLM_API_KEY=…
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-9rem)] min-h-[26rem] w-full max-w-3xl flex-col gap-4">
      {/* Header: the model is display-only (the key never travels); the
          reset button starts a fresh conversation, dropping the cards and
          the log together with the server-side thread swap. */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-text-primary">
            {t("nav.assistant")}
          </h1>
          {status.model && (
            <p className="text-xs text-text-muted">
              {t("assistant.model")}: {status.model}
            </p>
          )}
        </div>
        <Button variant="ghost" onClick={handleReset} disabled={busy}>
          <RefreshCw size={16} />
          {t("assistant.newChat")}
        </Button>
      </div>

      {/* The log: user and assistant bubbles, then the pending cards.
          Both scroll together in one area pinned between the header and
          the input, so long conversations never push the input off
          screen (mobile included). */}
      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && !pending && (
          <div className="rounded-2xl border border-border bg-surface-1 px-4 py-6 text-center text-sm text-text-muted">
            {t("assistant.empty")}
          </div>
        )}
        {messages.map((message, index) => (
          <div
            key={index}
            className={cn(
              "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm",
              message.role === "user"
                ? "ml-auto bg-surface-2 text-text-primary"
                : "mr-auto border bg-surface-1 text-text-primary",
              message.isError && "border-danger/40"
            )}
          >
            {message.text}
          </div>
        ))}

        {pending && (
          <div className="mr-auto max-w-[92%] space-y-2 rounded-2xl border border-danger/30 bg-surface-1 p-4">
            <p className="text-sm font-medium text-text-primary">{t("assistant.confirm.title")}</p>
            {pending.map((call) => {
              const decidedThis = decided[call.id];
              return (
                <div key={call.id} className="rounded-lg border border-border bg-surface-0 p-3">
                  <p className="text-sm font-medium text-text-primary">
                    {actionLabel(call.name, t)}
                  </p>
                  {Object.keys(call.args).length > 0 && (
                    <p className="mt-1 break-all font-mono text-xs text-text-muted">
                      {formatArgs(call.args, call.names, t)}
                    </p>
                  )}
                  {call.duplicates && call.duplicates.length > 0 && (
                    <div className="mt-2 rounded-md bg-danger/10 px-2 py-1.5 text-xs text-danger">
                      <p>{t("assistant.duplicates")}</p>
                      {call.duplicates.map((duplicate) => (
                        <p key={duplicate.id}>
                          #{duplicate.id} — {duplicate.date}, {duplicate.amount}, {duplicate.description}
                        </p>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      variant={decidedThis === true ? "primary" : "secondary"}
                      onClick={() => handleDecide(call, true)}
                      disabled={busy || decidedThis !== undefined}
                    >
                      {t("assistant.confirm.approve")}
                    </Button>
                    <Button
                      variant={decidedThis === false ? "danger" : "ghost"}
                      onClick={() => handleDecide(call, false)}
                      disabled={busy || decidedThis !== undefined}
                    >
                      {t("assistant.confirm.decline")}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Free input locks while a confirmation is on the table — the
          cards are the only way forward, same as the terminal's y/n
          prompt refusing any other answer. */}
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          handleSend();
        }}
      >
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={busy ? t("assistant.thinking") : t("assistant.placeholder")}
          disabled={busy || pending !== null}
          maxLength={4000}
        />
        <Button type="submit" disabled={busy || pending !== null || !input.trim()}>
          <Send size={16} />
          {t("assistant.send")}
        </Button>
      </form>
    </div>
  );
}
