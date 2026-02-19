import { useState, useRef, useEffect, useCallback } from "react";
import type {
  Message,
  StartSessionResponse,
  ChatMessageResponse,
  IntakeReport,
} from "../types";
import "./ChatWidget.css";

const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/chat`
  : "/api/chat";

export function ChatWidget() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [report, setReport] = useState<IntakeReport | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [caseType, setCaseType] = useState<string | null>(null);
  const [readyForReport, setReadyForReport] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const addMessage = (role: "user" | "assistant", content: string) => {
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role, content, timestamp: Date.now() },
    ]);
  };

  const startSession = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/start`, { method: "POST" });
      const data: StartSessionResponse = await res.json();
      setSessionId(data.session_id);
      addMessage("assistant", data.message);
    } catch {
      addMessage(
        "assistant",
        "Sorry, I'm having trouble connecting. Please refresh and try again.",
      );
    }
  }, []);

  useEffect(() => {
    startSession();
  }, [startSession]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || !sessionId || isLoading) return;

    addMessage("user", text);
    setInput("");
    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      const data: ChatMessageResponse = await res.json();
      addMessage("assistant", data.message);

      if (data.case_type) setCaseType(data.case_type);
      if (data.ready_for_report) {
        setReadyForReport(true);
        fetchReport();
      }
    } catch {
      addMessage("assistant", "Sorry, something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  const fetchReport = async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API_BASE}/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (res.ok) {
        const data: IntakeReport = await res.json();
        setReport(data);
      }
    } catch {
      /* report fetch is non-critical */
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const caseTypeLabel =
    caseType === "dwi"
      ? "DWI Case"
      : caseType === "parking_ticket"
        ? "Parking Ticket"
        : null;

  return (
    <div className="chat-container">
      <div className="chat-widget">
        {/* Header */}
        <div className="chat-header">
          <div className="header-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div className="header-text">
            <h1>Legal Intake Assistant</h1>
            <p>
              {caseTypeLabel
                ? `Discussing: ${caseTypeLabel}`
                : "Tell us about your case"}
            </p>
          </div>
          {readyForReport && report && (
            <button
              className="report-toggle"
              onClick={() => setShowReport(!showReport)}
            >
              {showReport ? "Chat" : "Report"}
            </button>
          )}
        </div>

        {/* Body */}
        {showReport && report ? (
          <ReportView report={report} />
        ) : (
          <>
            <div className="chat-messages">
              {messages.map((msg) => (
                <div key={msg.id} className={`message ${msg.role}`}>
                  {msg.role === "assistant" && (
                    <div className="avatar">
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                      >
                        <path
                          d="M12 2L2 7l10 5 10-5-10-5z"
                          stroke="currentColor"
                          strokeWidth="2"
                        />
                      </svg>
                    </div>
                  )}
                  <div className="bubble">{msg.content}</div>
                </div>
              ))}

              {isLoading && (
                <div className="message assistant">
                  <div className="avatar">
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                    >
                      <path
                        d="M12 2L2 7l10 5 10-5-10-5z"
                        stroke="currentColor"
                        strokeWidth="2"
                      />
                    </svg>
                  </div>
                  <div className="bubble typing">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="chat-input">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  readyForReport
                    ? "Anything else to add?"
                    : "Type your message..."
                }
                disabled={isLoading}
              />
              <button
                onClick={sendMessage}
                disabled={isLoading || !input.trim()}
                aria-label="Send"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </>
        )}
      </div>
      <p className="disclaimer">
        This is not legal advice. Preliminary intake only.
      </p>
    </div>
  );
}

function ReportView({ report }: { report: IntakeReport }) {
  const recClass =
    report.recommendation === "take"
      ? "rec-take"
      : report.recommendation === "pass"
        ? "rec-pass"
        : "rec-review";

  const strengthClass =
    report.case_strength === "strong"
      ? "strength-strong"
      : report.case_strength === "moderate"
        ? "strength-moderate"
        : "strength-weak";

  return (
    <div className="report-view">
      <div className="report-header-bar">
        <h2>{report.case_type_display}</h2>
        <div className="report-badges">
          <span className={`badge ${recClass}`}>{report.recommendation}</span>
          <span className={`badge ${strengthClass}`}>
            {report.case_strength}
          </span>
        </div>
      </div>

      <section>
        <h3>Summary</h3>
        <p>{report.client_summary}</p>
      </section>

      <section>
        <h3>Classification</h3>
        <p>
          <strong>{report.offense_classification}</strong>
        </p>
        <p className="muted">{report.potential_penalties}</p>
      </section>

      {report.identified_defenses.length > 0 && (
        <section>
          <h3>Potential Defenses</h3>
          <ul>
            {report.identified_defenses.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </section>
      )}

      <div className="report-flags">
        {report.green_flags.length > 0 && (
          <section className="flags-green">
            <h3>Positive Factors</h3>
            <ul>
              {report.green_flags.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </section>
        )}
        {report.red_flags.length > 0 && (
          <section className="flags-red">
            <h3>Concerns</h3>
            <ul>
              {report.red_flags.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <section>
        <h3>Recommendation</h3>
        <p>{report.recommendation_reasoning}</p>
      </section>

      {report.next_steps.length > 0 && (
        <section>
          <h3>Next Steps</h3>
          <ol>
            {report.next_steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
