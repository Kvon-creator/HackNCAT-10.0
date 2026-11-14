import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { getCurrentAccount, signIn, signOut } from "./auth";
import { ApiError, createCalendarEvent, getOpportunities, getProfile, setSaved, syncInbox, updatePreferences } from "./services/api";
import type { Opportunity, Preferences, Profile, SyncResult } from "./types";

const categories = ["internship", "scholarship", "research", "event", "academic", "emergency", "general", "other"];

function friendlyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session expired. Sign in again to continue.";
    if (error.status === 403) return error.message || "Microsoft access needs consent or account verification.";
    if (error.status === 429) return "Too many requests. Wait a moment and try again.";
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

function localDateTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function addHoursLocal(value: string, hours: number): string {
  const date = new Date(value);
  date.setHours(date.getHours() + hours);
  return localDateTime(date.toISOString());
}

function localDate(value: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

function opportunityDateLabel(item: Opportunity): string | null {
  if (item.deadline_date && !item.event_start) {
    const [year, month, day] = item.deadline_date.split("-").map(Number);
    const date = new Date(year, month - 1, day, 12);
    return `Deadline ${date.toLocaleDateString([], { dateStyle: "medium" })}`;
  }
  const value = item.event_start || item.deadline_at;
  return value ? `When ${new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` : "";
}

function OpportunityCard({
  item,
  onSave,
  onCalendar,
  busy,
}: {
  item: Opportunity;
  onSave: (item: Opportunity) => void;
  onCalendar: (item: Opportunity) => void;
  busy: boolean;
}) {
  return (
    <article className="opportunity-card">
      <div className="card-topline">
        <span className={`priority priority-${item.priority}`}>{item.priority}</span>
        <span className="category-label">{item.category}</span>
        {item.needs_review && <span className="review-label">Check details</span>}
      </div>
      <h2>{item.title}</h2>
      <p className="summary">{item.summary}</p>
      <div className="why-row">
        <span className="score">{item.relevance_score}% match</span>
        <span>{item.relevance_reason}</span>
      </div>
      <div className="card-meta">
        {opportunityDateLabel(item) && <span>{opportunityDateLabel(item)}</span>}
        {item.location && <span>{item.location}</span>}
      </div>
      <div className="card-actions">
        {item.source_link && <a className="text-link" href={item.source_link} target="_blank" rel="noreferrer">Open original Outlook message <span aria-hidden="true">↗</span></a>}
        <div className="action-group">
          <button className="button button-quiet" disabled={busy} onClick={() => onSave(item)} aria-pressed={item.saved}>{item.saved ? "Saved" : "Save"}</button>
          <button className="button button-outline" onClick={() => onCalendar(item)}>{item.calendar_status === "added" ? "Add again" : "Add to calendar"}</button>
        </div>
      </div>
    </article>
  );
}

function PreferencesPanel({ profile, onSaved }: { profile: Profile; onSaved: (profile: Profile) => void }) {
  const [form, setForm] = useState<Preferences>(profile.preferences);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const commaList = (values: string[]) => values.join(", ");
  const splitList = (value: string) => value.split(",").map((word) => word.trim()).filter(Boolean);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const result = await updatePreferences(form);
      onSaved(result);
    } catch (cause) {
      setError(friendlyError(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="preferences-panel">
      <div className="section-heading"><div><p className="eyebrow">YOUR PROFILE</p><h2>Make your feed yours</h2></div><p>Change a few details to update how opportunities are ranked.</p></div>
      <form className="preferences-form" onSubmit={submit}>
        <label>Major<input value={form.major || ""} onChange={(e) => setForm({ ...form, major: e.target.value || null })} placeholder="Computer science" /></label>
        <label>Academic level<input value={form.academic_level || ""} onChange={(e) => setForm({ ...form, academic_level: e.target.value || null })} placeholder="Junior" /></label>
        <label>Interests <span className="label-hint">comma separated</span><input value={commaList(form.interests)} onChange={(e) => setForm({ ...form, interests: splitList(e.target.value) })} placeholder="Internships, robotics" /></label>
        <label>Organizations <span className="label-hint">comma separated</span><input value={commaList(form.organizations)} onChange={(e) => setForm({ ...form, organizations: splitList(e.target.value) })} placeholder="NSBE, SWE" /></label>
        <label className="wide-field">Career goals <span className="label-hint">comma separated</span><input value={commaList(form.career_goals)} onChange={(e) => setForm({ ...form, career_goals: splitList(e.target.value) })} placeholder="Product design, public service" /></label>
        <label className="reminders-toggle"><input type="checkbox" checked={form.show_reminders} onChange={(e) => setForm({ ...form, show_reminders: e.target.checked })} /> Show in-app reminders</label>
        <div className="form-footer"><button className="button button-maroon" disabled={saving}>{saving ? "Saving…" : "Save preferences"}</button>{error && <p className="inline-error" role="alert">{error}</p>}</div>
      </form>
    </section>
  );
}

function CalendarDialog({ item, onClose, onCreated }: { item: Opportunity; onClose: () => void; onCreated: (result: { web_link: string | null; simulated: boolean }) => void }) {
  const isDeadline = !item.event_start && Boolean(item.deadline_date);
  const initialStart = item.event_start ? localDateTime(item.event_start) : item.deadline_at ? localDateTime(item.deadline_at) : "";
  const [allDay, setAllDay] = useState(isDeadline);
  const [start, setStart] = useState(isDeadline ? item.deadline_date || "" : initialStart);
  const [end, setEnd] = useState(() => {
    if (isDeadline && item.deadline_date) {
      const next = new Date(`${item.deadline_date}T12:00:00`);
      next.setDate(next.getDate() + 1);
      return localDate(next);
    }
    return item.event_end ? localDateTime(item.event_end) : (initialStart ? addHoursLocal(initialStart, 1) : "");
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{ web_link: string | null; simulated: boolean } | null>(null);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = await createCalendarEvent({
        opportunity_id: item.id,
        confirmed: true,
        all_day: allDay,
        start: allDay ? start : new Date(start).toISOString(),
        end: allDay ? end : new Date(end).toISOString(),
        time_zone: zone,
      });
      setResult({ web_link: payload.web_link, simulated: payload.simulated });
      onCreated({ web_link: payload.web_link, simulated: payload.simulated });
    } catch (cause) {
      setError(friendlyError(cause));
    } finally {
      setBusy(false);
    }
  }

  return <div className="modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="calendar-title">
      <button className="dialog-close" aria-label="Close" onClick={onClose}>×</button>
      {result ? <div className="success-state"><span className="success-mark">✓</span><p className="eyebrow">CALENDAR UPDATED</p><h2 id="calendar-title">Event confirmed</h2><p>{result.simulated ? "This is a simulated calendar event for the demo." : "Your event was added to Outlook Calendar."}</p>{result.web_link && <a className="button button-maroon" href={result.web_link} target="_blank" rel="noreferrer">View in Outlook</a>}<button className="button button-quiet" onClick={onClose}>Done</button></div> : <>
        <p className="eyebrow">OUTLOOK CALENDAR</p><h2 id="calendar-title">Confirm this event</h2><p className="dialog-subtitle">Review the time before adding <strong>{item.title}</strong> to your calendar.</p>
        <form className="calendar-form" onSubmit={submit}>
          <label className="checkbox-line"><input type="checkbox" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} /> All-day event</label>
          <label>Start<input required type={allDay ? "date" : "datetime-local"} value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label>{allDay ? "End date (exclusive)" : "End"}<input required type={allDay ? "date" : "datetime-local"} value={end} onChange={(e) => setEnd(e.target.value)} /></label>
          <p className="timezone-note">Time zone: {zone}</p>
          {error && <p className="inline-error" role="alert">{error}</p>}
          <div className="dialog-actions"><button type="button" className="button button-quiet" onClick={onClose}>Cancel</button><button className="button button-maroon" disabled={busy || !start || !end}>{busy ? "Adding…" : "Confirm and add"}</button></div>
        </form>
      </>}
    </section>
  </div>;
}

export default function App() {
  const [accountName, setAccountName] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [items, setItems] = useState<Opportunity[]>([]);
  const [tab, setTab] = useState<"feed" | "saved" | "preferences">("feed");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [priority, setPriority] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeCalendar, setActiveCalendar] = useState<Opportunity | null>(null);
  const [savingIds, setSavingIds] = useState<string[]>([]);
  const signedIn = Boolean(accountName);
  const shownItems = useMemo(() => tab === "saved" ? items.filter((item) => item.saved) : items, [items, tab]);

  async function loadDashboard(filters: { q?: string; category?: string; priority?: string } = {}) {
    setLoading(true);
    setError("");
    try {
      const [me, feed] = await Promise.all([getProfile(), getOpportunities(filters)]);
      setProfile(me);
      setItems(feed.items);
      setAccountName(me.display_name || "Signed in");
    } catch (cause) {
      setError(friendlyError(cause));
      if (cause instanceof ApiError && cause.status === 401) setAccountName("");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!import.meta.env.VITE_MS_CLIENT_ID || !import.meta.env.VITE_MS_TENANT_ID || !import.meta.env.VITE_MS_API_SCOPE) return;
    getCurrentAccount().then((account) => {
      if (account) {
        setAccountName(account.name || account.username);
        void loadDashboard();
      }
    }).catch((cause: unknown) => setError(friendlyError(cause)));
    // Run once at launch; auth state changes only through the buttons below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSignIn() {
    setError("");
    setLoading(true);
    try {
      const account = await signIn();
      setAccountName(account.name || account.username);
      await loadDashboard();
    } catch (cause) {
      setError(friendlyError(cause));
      setLoading(false);
    }
  }

  async function handleSignOut() {
    try {
      await signOut();
    } finally {
      setAccountName("");
      setProfile(null);
      setItems([]);
      setNotice("");
    }
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    const filters = { q: query, category, priority };
    setSearch(query);
    await loadDashboard(filters);
  }

  async function handleSync() {
    setSyncing(true);
    setError("");
    setNotice("");
    try {
      const result = await syncInbox();
      setSyncResult(result);
      setNotice(`Inbox refresh complete: ${result.imported} new opportunities, ${result.unchanged} unchanged.`);
      await loadDashboard({ q: search, category, priority });
    } catch (cause) {
      setError(friendlyError(cause));
    } finally {
      setSyncing(false);
    }
  }

  async function handleSave(item: Opportunity) {
    setSavingIds((ids) => [...ids, item.id]);
    setError("");
    try {
      await setSaved(item.id, !item.saved);
      setItems((current) => current.map((row) => row.id === item.id ? { ...row, saved: !item.saved } : row));
    } catch (cause) {
      setError(friendlyError(cause));
    } finally {
      setSavingIds((ids) => ids.filter((id) => id !== item.id));
    }
  }

  const authConfigured = Boolean(import.meta.env.VITE_MS_CLIENT_ID && import.meta.env.VITE_MS_TENANT_ID && import.meta.env.VITE_MS_API_SCOPE);

  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#top" aria-label="AggieConnect home"><span className="brand-mark">A</span><span>Aggie<span className="brand-light">Connect</span></span></a>
      <div className="topbar-right">{profile?.mode === "demo" && <span className="demo-pill">DEMO MODE</span>}{signedIn ? <><span className="account-label">{accountName}</span><button className="signout-button" onClick={handleSignOut}>Sign out</button></> : <span className="topbar-caption">Your opportunities, connected</span>}</div>
    </header>
    <main id="top">
      {!signedIn ? <section className="welcome-hero">
        <div className="hero-copy"><p className="eyebrow">YOUR NEXT OPPORTUNITY STARTS HERE</p><h1>Make room for<br /><em>what’s next.</em></h1><p className="hero-description">A clearer way to find the internships, scholarships, research, and campus events waiting in your inbox.</p>
          {!authConfigured && <p className="config-message">Microsoft sign-in is not configured yet. Add the Vite client ID, tenant ID, and API scope to your local environment.</p>}
          <button className="button button-maroon sign-in-button" disabled={!authConfigured || loading} onClick={handleSignIn}>{loading ? "Connecting…" : "Continue with Microsoft"}<span aria-hidden="true">→</span></button>
          <p className="privacy-note"><span aria-hidden="true">▣</span> Your Outlook remains yours. You choose what to save and add to your calendar.</p>
        </div>
        <div className="hero-art" aria-hidden="true"><div className="hero-circle"><span className="hero-star">✳</span><span className="hero-art-word">OPPORTUNITY<br />IS CLOSER</span><span className="hero-art-small">AGGIECONNECT · COLLEGE OF ENGINEERING</span></div><div className="hero-card hero-card-one"><span className="mini-dot" /> Internship match <strong>80%</strong></div><div className="hero-card hero-card-two">✦ &nbsp; Made for Aggies</div></div>
      </section> : <>
        <section className="dashboard-intro"><div><p className="eyebrow">AGGIECONNECT FEED</p><h1>Good to see you, <em>{(profile?.display_name || accountName).split(" ")[0]}.</em></h1><p className="intro-copy">A focused view of what’s worth your attention.</p></div><button className="button button-maroon sync-button" onClick={handleSync} disabled={syncing || loading}><span className={syncing ? "spin" : ""}>↻</span> {syncing ? "Refreshing inbox…" : "Refresh inbox"}</button></section>
        {notice && <div className="notice-banner" role="status"><span>✓</span>{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button></div>}
        {syncResult && !notice && <span className="sr-only">Latest inbox refresh imported {syncResult.imported} items.</span>}
        <nav className="tabs" aria-label="Main sections"><button className={tab === "feed" ? "tab active" : "tab"} onClick={() => setTab("feed")}>For you</button><button className={tab === "saved" ? "tab active" : "tab"} onClick={() => setTab("saved")}>Saved <span className="tab-count">{items.filter((item) => item.saved).length}</span></button><button className={tab === "preferences" ? "tab active" : "tab"} onClick={() => setTab("preferences")}>Preferences</button></nav>
        {tab === "preferences" && profile ? <PreferencesPanel profile={profile} onSaved={(updated) => { setProfile(updated); setNotice("Preferences saved. Your feed will reflect your updated interests."); setTab("feed"); void loadDashboard({ q: search, category, priority }); }} /> : <>
          <section className="feed-toolbar"><div><h2>{tab === "saved" ? "Your saved opportunities" : "A little closer to your goals"}</h2><p>{tab === "saved" ? "Keep the ones you want to come back to." : "Ranked around your interests and goals."}</p></div>
            <form className="search-form" onSubmit={handleSearch}><label className="sr-only" htmlFor="search-opps">Search opportunities</label><span aria-hidden="true">⌕</span><input id="search-opps" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search opportunities" /><button aria-label="Search" type="submit">Search</button></form>
          </section>
          <form className="filter-row" onSubmit={handleSearch}><label>Category<select value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>{categories.map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select></label><label>Priority<select value={priority} onChange={(e) => setPriority(e.target.value)}><option value="">All priorities</option>{["emergency", "urgent", "deadline", "general"].map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}</select></label><button className="filter-apply" type="submit">Apply filters</button></form>
          {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError("")}>Dismiss</button></div>}
          {loading ? <div className="loading-state"><span className="spinner" /><p>Finding opportunities for you…</p></div> : shownItems.length ? <section className="opportunity-grid" aria-label="Opportunities">{shownItems.map((item) => <OpportunityCard key={item.id} item={item} onSave={handleSave} onCalendar={setActiveCalendar} busy={savingIds.includes(item.id)} />)}</section> : <section className="empty-state"><span className="empty-icon">✳</span><h2>{tab === "saved" ? "Nothing saved yet" : "Your feed is ready for a refresh"}</h2><p>{tab === "saved" ? "Save an opportunity to keep it close." : "Refresh your inbox to look for recent announcements and opportunities."}</p>{tab === "feed" && <button className="button button-maroon" onClick={handleSync} disabled={syncing}>{syncing ? "Refreshing…" : "Refresh inbox"}</button>}</section>}
        </>}
      </>}
      {!signedIn && error && <p className="welcome-error" role="alert">{error}</p>}
    </main>
    <footer className="footer"><span>AggieConnect</span><span>Built for Aggies, with care for your inbox.</span><a href="https://www.tamusa.edu/" target="_blank" rel="noreferrer">Texas A&amp;M University–San Antonio ↗</a></footer>
    {activeCalendar && <CalendarDialog item={activeCalendar} onClose={() => setActiveCalendar(null)} onCreated={() => { setActiveCalendar(null); setNotice("Calendar event created."); void loadDashboard({ q: search, category, priority }); }} />}
  </div>;
}
