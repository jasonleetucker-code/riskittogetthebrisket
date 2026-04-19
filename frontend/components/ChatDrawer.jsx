"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useAuthContext } from "@/app/AppShellWrapper";

const STORAGE_KEY = "risk-brisket-chat-history-v1";
const MAX_HISTORY_TURNS = 60; // cap localStorage growth

const SUGGESTIONS = [
  "Compare Drake Maye and Lamar Jackson — who should I hold?",
  "Which IDPs have the tightest source agreement right now?",
  "What's a good sell-high on Ja'Marr Chase?",
  "Show me buy-low candidates under age 25",
  "Why is Carson Schwesinger ranked where he is?",
];

export default function ChatDrawer() {
  const { authenticated } = useAuthContext();
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [streamError, setStreamError] = useState("");
  const [usage, setUsage] = useState(null);
  const scrollRef = useRef(null);
  const abortRef = useRef(null);
  const inputRef = useRef(null);

  // Hydrate persisted conversation on mount.  ``useState`` initializer
  // doesn't run on hydration-safe paths (Next.js SSR); doing it in
  // an effect avoids the hydration mismatch warning.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          setMessages(parsed.slice(-MAX_HISTORY_TURNS));
        }
      }
    } catch {
      /* ignore corrupt storage */
    }
  }, []);

  // Persist on every change.  Capped to ``MAX_HISTORY_TURNS`` to
  // keep localStorage under quota even after months of use.
  useEffect(() => {
    try {
      const bounded = messages.slice(-MAX_HISTORY_TURNS);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(bounded));
    } catch {
      /* storage quota / SSR — silently ignore */
    }
  }, [messages]);

  // Auto-scroll to bottom on every streaming tick.  ``behavior:
  // "auto"`` because smooth-scrolling during a stream feels laggy.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streamingText, isOpen]);

  // Focus input whenever the drawer opens.
  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Esc closes the drawer (only when open).
  useEffect(() => {
    if (!isOpen) return;
    function onKey(e) {
      if (e.key === "Escape" && !isStreaming) setIsOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, isStreaming]);

  const sendMessage = useCallback(
    async (text) => {
      const trimmed = (text || "").trim();
      if (!trimmed || isStreaming) return;

      const nextHistory = [...messages, { role: "user", content: trimmed }];
      setMessages(nextHistory);
      setInput("");
      setIsStreaming(true);
      setStreamingText("");
      setStreamError("");
      setUsage(null);

      const controller = new AbortController();
      abortRef.current = controller;

      let accumulated = "";
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: nextHistory }),
          signal: controller.signal,
          credentials: "same-origin",
        });

        if (!res.ok) {
          let errText = `HTTP ${res.status}`;
          try {
            const body = await res.json();
            if (body?.error) errText = body.error;
          } catch {
            /* ignore */
          }
          setMessages([
            ...nextHistory,
            { role: "assistant", content: `_${errText}_` },
          ]);
          setStreamError(errText);
          return;
        }

        // Parse SSE stream.  Each event is ``data: {JSON}\n\n``.
        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Events are separated by blank lines.
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";

          for (const rawEvent of parts) {
            const dataLine = rawEvent
              .split("\n")
              .find((ln) => ln.startsWith("data: "));
            if (!dataLine) continue;
            const jsonStr = dataLine.slice(6);
            let payload;
            try {
              payload = JSON.parse(jsonStr);
            } catch {
              continue;
            }

            if (payload.type === "text" && typeof payload.text === "string") {
              accumulated += payload.text;
              setStreamingText(accumulated);
            } else if (payload.type === "usage") {
              setUsage({
                inputTokens: payload.input_tokens || 0,
                outputTokens: payload.output_tokens || 0,
                cacheRead: payload.cache_read_input_tokens || 0,
                cacheWrite: payload.cache_creation_input_tokens || 0,
              });
            } else if (payload.type === "error") {
              accumulated +=
                (accumulated ? "\n\n" : "") + `**Error:** ${payload.error}`;
              setStreamingText(accumulated);
              setStreamError(payload.error || "Stream error");
            }
          }
        }

        // Flush the accumulated text into the history as a new
        // assistant message; clear the streaming-preview state.
        setMessages([
          ...nextHistory,
          { role: "assistant", content: accumulated || "_(no response)_" },
        ]);
      } catch (exc) {
        if (exc.name === "AbortError") {
          // User hit Stop mid-stream — keep whatever we got.
          setMessages([
            ...nextHistory,
            {
              role: "assistant",
              content: accumulated + "\n\n_(stopped)_",
            },
          ]);
        } else {
          const msg = exc?.message || String(exc);
          setMessages([
            ...nextHistory,
            { role: "assistant", content: `_Network error: ${msg}_` },
          ]);
          setStreamError(msg);
        }
      } finally {
        setStreamingText("");
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [messages, isStreaming],
  );

  const stopStreaming = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
  }, []);

  const clearHistory = useCallback(() => {
    if (isStreaming) return;
    if (messages.length === 0) return;
    if (!window.confirm("Clear the chat history?")) return;
    setMessages([]);
    setStreamingText("");
    setUsage(null);
    setStreamError("");
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, [isStreaming, messages.length]);

  const onSubmit = useCallback(
    (e) => {
      e.preventDefault();
      sendMessage(input);
    },
    [input, sendMessage],
  );

  const sawFirstTurn = messages.length > 0 || streamingText;

  // Never render for unauthenticated users — the ChatDrawer is
  // wired to the private ``/api/chat`` endpoint (owner-only) and
  // the floating trigger button would be a confusing dead-end for
  // anyone else.
  if (!authenticated) return null;

  return (
    <>
      {!isOpen && (
        <button
          type="button"
          className="chat-fab"
          onClick={() => setIsOpen(true)}
          aria-label="Open chat"
          title="Ask about the board"
        >
          <span className="chat-fab-glyph" aria-hidden>
            ▲
          </span>
          <span className="chat-fab-label">Ask</span>
        </button>
      )}

      {isOpen && (
        <div className="chat-overlay">
          <div
            className="chat-backdrop"
            onClick={() => !isStreaming && setIsOpen(false)}
          />
          <aside
            className="chat-drawer"
            role="dialog"
            aria-label="Chat with Claude about your board"
          >
            <header className="chat-header">
              <div className="chat-title">
                <span className="chat-title-dot" aria-hidden />
                <span>Ask the board</span>
              </div>
              <div className="chat-header-actions">
                {sawFirstTurn && !isStreaming && (
                  <button
                    type="button"
                    className="chat-mini-button"
                    onClick={clearHistory}
                    title="Clear chat history"
                  >
                    Clear
                  </button>
                )}
                <button
                  type="button"
                  className="chat-mini-button"
                  onClick={() => setIsOpen(false)}
                  title="Close"
                  disabled={isStreaming}
                >
                  ✕
                </button>
              </div>
            </header>

            <div className="chat-scroll" ref={scrollRef}>
              {!sawFirstTurn && (
                <div className="chat-suggestions">
                  <div className="chat-suggestions-title">Try asking…</div>
                  {SUGGESTIONS.map((s, i) => (
                    <button
                      key={i}
                      type="button"
                      className="chat-suggestion"
                      onClick={() => sendMessage(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}

              {messages.map((m, i) => (
                <ChatBubble key={i} role={m.role} content={m.content} />
              ))}

              {streamingText && (
                <ChatBubble role="assistant" content={streamingText} streaming />
              )}

              {isStreaming && !streamingText && (
                <div className="chat-thinking">
                  <span className="chat-thinking-dot" />
                  <span className="chat-thinking-dot" />
                  <span className="chat-thinking-dot" />
                </div>
              )}

              {usage && (
                <div className="chat-usage" title="Token usage for last turn">
                  in {usage.inputTokens} · out {usage.outputTokens}
                  {usage.cacheRead > 0 && ` · cache read ${usage.cacheRead}`}
                  {usage.cacheWrite > 0 && ` · cache write ${usage.cacheWrite}`}
                </div>
              )}
            </div>

            <form className="chat-input-row" onSubmit={onSubmit}>
              <input
                ref={inputRef}
                type="text"
                className="chat-input"
                placeholder={
                  isStreaming
                    ? "Streaming…"
                    : "Ask about the board…"
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={isStreaming}
                autoComplete="off"
              />
              {isStreaming ? (
                <button
                  type="button"
                  className="chat-submit chat-stop"
                  onClick={stopStreaming}
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  className="chat-submit"
                  disabled={!input.trim()}
                >
                  Send
                </button>
              )}
            </form>
          </aside>
        </div>
      )}
    </>
  );
}

function ChatBubble({ role, content, streaming = false }) {
  const isUser = role === "user";
  const className = useMemo(() => {
    const cls = ["chat-bubble"];
    cls.push(isUser ? "chat-bubble-user" : "chat-bubble-assistant");
    if (streaming) cls.push("chat-bubble-streaming");
    return cls.join(" ");
  }, [isUser, streaming]);

  return (
    <div className={className}>
      <div className="chat-bubble-role">{isUser ? "You" : "Claude"}</div>
      <div className="chat-bubble-body">
        <ReactMarkdown>{content || ""}</ReactMarkdown>
      </div>
    </div>
  );
}
