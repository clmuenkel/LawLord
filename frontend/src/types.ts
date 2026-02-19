export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

export interface StartSessionResponse {
  session_id: string;
  message: string;
}

export interface ChatMessageResponse {
  message: string;
  case_type: string | null;
  ready_for_report: boolean;
}

export interface IntakeReport {
  session_id: string;
  case_type: string;
  case_type_display: string;
  jurisdiction: string;
  client_summary: string;
  key_facts: Record<string, string>;
  offense_classification: string;
  potential_penalties: string;
  identified_defenses: string[];
  red_flags: string[];
  green_flags: string[];
  case_strength: "weak" | "moderate" | "strong";
  recommendation: "take" | "pass" | "needs_review";
  recommendation_reasoning: string;
  next_steps: string[];
}
