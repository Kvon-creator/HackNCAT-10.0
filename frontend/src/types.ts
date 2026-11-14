export type Priority = "emergency" | "urgent" | "deadline" | "general";
export type Category = "internship" | "scholarship" | "research" | "event" | "academic" | "emergency" | "general" | "other";

export interface Preferences {
  major: string | null;
  academic_level: string | null;
  interests: string[];
  organizations: string[];
  career_goals: string[];
  show_reminders: boolean;
}

export interface Profile {
  id: string;
  display_name: string | null;
  preferences: Preferences;
  mode?: "live" | "demo";
}

export interface Opportunity {
  id: string;
  title: string;
  summary: string;
  category: Category;
  priority: Priority;
  relevance_score: number;
  relevance_reason: string;
  source_link: string | null;
  event_start: string | null;
  event_end: string | null;
  deadline_at: string | null;
  deadline_date: string | null;
  location: string | null;
  needs_review: boolean;
  saved: boolean;
  calendar_status: "not_added" | "pending" | "added";
}

export interface FeedResponse {
  items: Opportunity[];
  total: number;
}

export interface SyncResult {
  fetched: number;
  imported: number;
  unchanged: number;
  skipped: number;
  failed: number;
}

export interface CalendarResult {
  id: string;
  status: string;
  web_link: string | null;
  simulated: boolean;
}
