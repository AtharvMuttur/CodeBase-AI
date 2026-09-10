import { useEffect, useMemo, useRef, useState } from "react";
import { api, ChunkCitation, RepositorySummary } from "../lib/api";
import { renderMarkdown } from "../lib/markdown";
import { highlightLine } from "../lib/highlight";
import { useToasts } from "./Toast";
import {
  SendIcon,
  StopIcon,
  CopyIcon,
  CheckIcon,
  SparklesIcon,
  FileCodeIcon,
  ChevronDownIcon,
} from "./Icons";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  citations?: ChunkCitation[];
  model?: string;
  repoId?: number | null;
  repoName?: string | null;
}

interface Props {
  repositoryId: number | null;
  /** Optional list of repositories so the chat can show a label per message. */
  repos?: RepositorySummary[];
}

const SUGGESTIONS = [
  "Where is the FastAPI app factory defined?",
  "How does the indexer process background jobs?",
  "What providers are supported for embeddings?",
  "Summarize the architecture of this codebase.",
];

export function Chat({ repositoryId, repos }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const { push } = useToasts();

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const repoName = useMemo(() => {
    if (repositoryId === null) return null;
    return repos?.find((r) => r.id === repositoryId)?.name ?? null;
  }, [repos, repositoryId]);

  useEffect(() => {
    setMessages([]);
  }, [repositoryId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pending]);

  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const ask = async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || pending) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      repoId: repositoryId,
      repoName,
    };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setPending(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const result = await api.query(trimmed, repositoryId, 5, controller.signal);
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.answer,
          citations: result.chunks,
          model: result.model,
          repoId: result.repository_id,
        },
      ]);
    } catch (err) {
      if ((err as DOMException)?.name === "AbortError") {
        setMessages((m) => [
          ...m,
          {
            id: crypto.randomUUID(),
            role: "error",
            content: "Stopped.",
          },
        ]);
        return;
      }
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "error",
          content: (err as Error).message,
        },
      ]);
      push("error", (err as Error).message);
    } finally {
      setPending(false);
      abortRef.current = null;
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    await ask(input);
  };

  const stop = () => {
    abortRef.current?.abort();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit(event);
    }
  };

  const onFormKeyDown = (event: React.KeyboardEvent<HTMLFormElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      composerRef.current?.focus();
    }
  };

  return (
    <section className="main">
      <div className="chat" ref={scrollRef}>
        {messages.length === 0 && !pending && (
          <div className="chat__welcome">
            <div className="chat__welcome-icon">
              <SparklesIcon size={26} />
            </div>
            <span className="chat__welcome-kicker">
              {repositoryId === null ? "Repository intelligence" : "Repository selected"}
            </span>
            <h2 className="chat__welcome-title">
              {repositoryId === null
                ? "Ask anything across your indexed code"
                : `Ask about ${repoName ?? "this repository"}`}
            </h2>
            <p className="chat__welcome-sub">
              Answers include citations to the source file and line range.
              Press <kbd>?</kbd> for keyboard shortcuts.
            </p>
            <div className="chat__welcome-rule" aria-hidden="true" />
            <div className="chat__suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat__suggestion"
                  onClick={() => ask(s)}
                  disabled={pending}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageView
            key={msg.id}
            message={msg}
            repos={repos}
            onCopy={() => push("info", "Copied to clipboard.")}
          />
        ))}
        {pending && (
          <div className="message">
            <div className="message__role">
              <span className="message__role-tag">
                <SparklesIcon size={13} />
                assistant
              </span>
            </div>
            <div className="message__body">
              <div className="typing" aria-label="Assistant is thinking">
                <span className="typing__dot" />
                <span className="typing__dot" />
                <span className="typing__dot" />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="composer">
        <form
          className="composer__inner"
          onSubmit={submit}
          onKeyDown={onFormKeyDown}
        >
          <textarea
            ref={composerRef}
            value={input}
            placeholder={
              repositoryId === null
                ? "Ask anything across all indexed repositories…"
                : "Ask about this repository…"
            }
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={false}
            rows={1}
            aria-label="Message"
          />
          {pending ? (
            <button
              type="button"
              className="composer__stop"
              onClick={stop}
              aria-label="Stop generating"
            >
              <StopIcon size={14} />
              Stop
            </button>
          ) : (
            <button
              type="submit"
              className="composer__send"
              disabled={!input.trim()}
              aria-label="Send"
            >
              <SendIcon size={14} />
              Send
            </button>
          )}
        </form>
        <div className="composer__hint">
          <kbd>Enter</kbd> send · <kbd>Shift</kbd>+<kbd>Enter</kbd> newline ·
          <kbd>Ctrl</kbd>+<kbd>K</kbd> focus composer · <kbd>?</kbd> shortcuts
        </div>
      </div>
    </section>
  );
}

function MessageView({
  message,
  repos,
  onCopy,
}: {
  message: ChatMessage;
  repos?: RepositorySummary[];
  onCopy: (text: string) => void;
}) {
  const isUser = message.role === "user";
  const isError = message.role === "error";
  const [copied, setCopied] = useState(false);
  const body = useMemo(() => {
    if (isUser) return null;
    return renderMarkdown(message.content);
  }, [message.content, isUser]);

  const repoLabel =
    message.repoName ??
    (message.repoId != null
      ? repos?.find((r) => r.id === message.repoId)?.name ?? null
      : null);

  const handleCopy = () => {
    void navigator.clipboard
      .writeText(message.content)
      .then(() => {
        setCopied(true);
        onCopy(message.content);
        window.setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        // clipboard blocked — silently fail
      });
  };

  return (
    <div
      className={`message ${isUser ? "message--user" : ""} ${isError ? "message--error" : ""}`}
    >
      <div className="message__role">
        <span className="message__role-tag">
          {!isUser && !isError && <SparklesIcon size={13} />}
          {message.role}
          {repoLabel && !isError && (
            <span style={{ color: "var(--fg-dim)", marginLeft: 6 }}>
              · {repoLabel}
            </span>
          )}
        </span>
        {!isUser && (
          <div className="message__actions">
            <button
              type="button"
              className={`message__action ${copied ? "copied" : ""}`}
              onClick={handleCopy}
              aria-label="Copy message"
              title="Copy message"
            >
              {copied ? (
                <>
                  <CheckIcon size={12} />
                  Copied
                </>
              ) : (
                <>
                  <CopyIcon size={12} />
                  Copy
                </>
              )}
            </button>
          </div>
        )}
      </div>
      {isUser ? (
        <div className="message__body">{message.content}</div>
      ) : (
        <div
          className="message__body"
          dangerouslySetInnerHTML={{ __html: body ?? "" }}
        />
      )}
      {message.model && (
        <div className="message__meta">
          <span className="message__meta-item">model: {message.model}</span>
          {message.citations && message.citations.length > 0 && (
            <span className="message__meta-item">
              {message.citations.length} citation
              {message.citations.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      )}
      {message.citations && message.citations.length > 0 && (
        <div className="citations">
          {message.citations.map((c, i) => (
            <CitationView key={c.chunk_id} citation={c} index={i + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function CitationView({
  citation,
  index,
}: {
  citation: ChunkCitation;
  index: number;
}) {
  const [expanded, setExpanded] = useState(false);

  const lines = useMemo(() => {
    const code = citation.content.split("\n");
    return code.map((line, i) => {
      const highlighted = highlightLine(
        line.length === 0 ? " " : line,
        citation.language,
      );
      return {
        n: citation.start_line + i,
        html: highlighted,
      };
    });
  }, [citation.content, citation.language, citation.start_line]);

  return (
    <div className={`citation ${expanded ? "citation--expanded" : "citation--collapsed"}`}>
      <header
        className="citation__header"
        onClick={() => setExpanded((v) => !v)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpanded((v) => !v);
          }
        }}
        aria-expanded={expanded}
      >
        <span className="citation__path" title={citation.file_path}>
          <FileCodeIcon size={13} />
          <span style={{ color: "var(--fg-dim)" }}>[{index}]</span>
          {citation.file_path}:{citation.start_line}-{citation.end_line}
        </span>
        <span className="citation__meta">
          <span>{citation.language ?? "text"}</span>
          <span className="citation__score">
            {citation.score.toFixed(3)}
          </span>
          <span className="citation__toggle">
            <ChevronDownIcon size={14} />
          </span>
        </span>
      </header>
      <pre className="citation__pre">
        {lines.map((l) => (
          <div key={l.n}>
            <span className="citation__line-number">{l.n}</span>
            <span dangerouslySetInnerHTML={{ __html: l.html }} />
          </div>
        ))}
      </pre>
    </div>
  );
}
