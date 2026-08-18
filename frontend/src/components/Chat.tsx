import { useEffect, useRef, useState } from "react";
import { api, ChunkCitation } from "../lib/api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  citations?: ChunkCitation[];
  model?: string;
}

interface Props {
  repositoryId: number | null;
}

/**
 * Chat panel. Holds the message history and the composer. The chat is
 * intentionally stateless on the server (Phase 1) — every POST /api/query
 * is independent.
 */
export function Chat({ repositoryId }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Reset the conversation when the user switches repositories.
  useEffect(() => {
    setMessages([]);
  }, [repositoryId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pending]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const question = input.trim();
    if (!question || pending) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
    };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setPending(true);

    try {
      const result = await api.query(question, repositoryId, 5);
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.answer,
          citations: result.chunks,
          model: result.model,
        },
      ]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          id: crypto.randomUUID(),
          role: "error",
          content: (err as Error).message,
        },
      ]);
    } finally {
      setPending(false);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit(event);
    }
  };

  return (
    <section className="main">
      <div className="chat" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            Ask a question about the indexed code. Citations link back to the
            source file and line range.
          </div>
        )}
        {messages.map((msg) => (
          <MessageView key={msg.id} message={msg} />
        ))}
        {pending && (
          <div className="message">
            <div className="role">assistant</div>
            <div className="body">Thinking…</div>
          </div>
        )}
      </div>

      <div className="composer">
        <form className="composer-inner" onSubmit={submit}>
          <textarea
            value={input}
            placeholder={
              repositoryId === null
                ? "Ask anything across all indexed repositories…"
                : "Ask about this repository…"
            }
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={pending}
            rows={2}
          />
          <button type="submit" disabled={pending || !input.trim()}>
            Send
          </button>
        </form>
        <div className="hint">Enter to send · Shift+Enter for newline</div>
      </div>
    </section>
  );
}

function MessageView({ message }: { message: ChatMessage }) {
  return (
    <div className={`message ${message.role}`}>
      <div className="role">{message.role}</div>
      <div className="body">{message.content}</div>
      {message.model && (
        <div className="meta" style={{ fontSize: 11, color: "var(--fg-dim)", marginTop: 6 }}>
          model: {message.model}
        </div>
      )}
      {message.citations && message.citations.length > 0 && (
        <div className="citations">
          {message.citations.map((c) => (
            <div className="citation" key={c.chunk_id}>
              <header>
                <span>
                  {c.file_path}:{c.start_line}-{c.end_line}
                </span>
                <span>
                  {c.language ?? "?"} · score {c.score.toFixed(3)}
                </span>
              </header>
              <pre>{c.content}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
