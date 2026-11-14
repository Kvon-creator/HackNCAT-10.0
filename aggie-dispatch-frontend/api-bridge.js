/*
 * Aggie Dispatch <-> AggieConnect API bridge.
 *
 * Replaces the static Home digest with the live, AI-ranked feed from the backend
 * (demo mode), using the page's own card pattern. If the API cannot be reached the
 * static sample content stays on screen, clearly labeled as a sample.
 *
 *   API base:  ?api=http://host:port/api   or window.AGGIE_API_BASE
 *              default http://127.0.0.1:8000/api
 *   Persona:   ?persona=cs|biz|bio  (otherwise the sidebar persona switcher)
 *
 * The page must be served from the backend's FRONTEND_ORIGIN (default
 * http://localhost:5173) or the browser will block the API calls (CORS).
 * Email-derived text is always inserted with textContent, never as HTML.
 */
(function () {
  'use strict';

  var ZONE = 'America/New_York';
  var OFFLINE_MESSAGE = "Can't reach AggieConnect right now. Try again in a moment.";

  // Sidebar personas -> preferences sent to PUT /api/me/preferences.
  var PERSONA_PREFS = {
    cs: {
      major: 'Computer Science', academic_level: 'Junior',
      interests: ['Internships', 'Machine Learning'], organizations: ['NSBE'],
      career_goals: ['Software Engineer'], show_reminders: true
    },
    biz: {
      major: 'Business Administration', academic_level: 'Junior',
      interests: ['Internships'], organizations: [], career_goals: [], show_reminders: true
    },
    bio: {
      major: 'Biology', academic_level: 'Sophomore',
      interests: ['Research'], organizations: [], career_goals: ['Graduate School'], show_reminders: true
    }
  };

  // Lane chips follow the page's existing digest chips (Urgent / Action Needed / Opportunity).
  var LANE_STYLE = {
    emergency: { label: 'Verified Emergency', chip: 'text-white bg-red-700', time: 'text-red-800' },
    urgent: { label: 'Urgent', chip: 'text-red-800 bg-red-100', time: 'text-red-800' },
    deadline: { label: 'Action Needed', chip: 'text-amber-950 bg-aggie-gold/40', time: 'text-red-800' },
    general: { label: 'Opportunity', chip: 'text-aggie-blue bg-blue-100', time: 'text-slate-500' }
  };
  var LANE_ORDER = ['emergency', 'urgent', 'deadline', 'general'];

  // Phone-size tap targets (44px) without changing the desktop look.
  var TAP = ' min-h-[44px] sm:min-h-0 inline-flex items-center';

  // ------------------------------------------------------------------ pure helpers

  function apiBase(search, override) {
    var params = new URLSearchParams(search || '');
    var base = params.get('api') || override || 'http://127.0.0.1:8000/api';
    return base.replace(/\/+$/, '');
  }

  // Add minutes to an ISO timestamp, keeping its original UTC offset.
  function addMinutesKeepOffset(iso, minutes) {
    var match = /([+-])(\d{2}):(\d{2})$/.exec(iso);
    var offsetMin = 0;
    var suffix = 'Z';
    if (match) {
      offsetMin = (match[1] === '-' ? -1 : 1) * (parseInt(match[2], 10) * 60 + parseInt(match[3], 10));
      suffix = match[0];
    }
    var ms = Date.parse(iso) + minutes * 60000;
    var wall = new Date(ms + offsetMin * 60000).toISOString().slice(0, 19);
    return wall + suffix;
  }

  function nextDate(ymd) {
    var d = new Date(ymd + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + 1);
    return d.toISOString().slice(0, 10);
  }

  // Calendar request for an opportunity, or null when it has no usable date.
  function calendarRequest(item) {
    if (item.event_start) {
      return {
        opportunity_id: item.id, confirmed: true, all_day: false,
        start: item.event_start, end: item.event_end || addMinutesKeepOffset(item.event_start, 60),
        time_zone: ZONE
      };
    }
    if (item.deadline_at) {
      return {
        opportunity_id: item.id, confirmed: true, all_day: false,
        start: item.deadline_at, end: addMinutesKeepOffset(item.deadline_at, 30), time_zone: ZONE
      };
    }
    if (item.deadline_date) {
      return {
        opportunity_id: item.id, confirmed: true, all_day: true,
        start: item.deadline_date, end: nextDate(item.deadline_date), time_zone: ZONE
      };
    }
    return null;
  }

  // Google Calendar "create event" link (no OAuth: the student reviews and clicks Save in Google).
  function toGoogleUtc(iso) {
    return new Date(Date.parse(iso)).toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  }

  function googleCalendarUrl(item) {
    var req = calendarRequest(item);
    if (!req) return null;
    var dates = req.all_day
      ? req.start.replace(/-/g, '') + '/' + req.end.replace(/-/g, '')
      : toGoogleUtc(req.start) + '/' + toGoogleUtc(req.end);
    var details = [item.summary, item.relevance_reason ? 'Why it matters to you: ' + item.relevance_reason : '',
      'Added from AggieConnect.'].filter(Boolean).join('\n\n');
    if (details.length > 1200) details = details.slice(0, 1197) + '...';
    var params = new URLSearchParams({ action: 'TEMPLATE', text: item.title || 'AggieConnect event', dates: dates, details: details, ctz: ZONE });
    if (item.location) params.set('location', item.location);
    return 'https://calendar.google.com/calendar/render?' + params.toString();
  }

  function localParts(iso) {
    var parts = {};
    new Intl.DateTimeFormat('en-US', {
      timeZone: ZONE, weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
    }).formatToParts(new Date(iso)).forEach(function (p) { parts[p.type] = p.value; });
    return parts;
  }

  function timeLabel(iso) {
    var p = localParts(iso);
    return p.hour + ':' + p.minute + ' ' + p.dayPeriod;
  }

  function dateLabel(iso) {
    var p = localParts(iso);
    return p.month + ' ' + p.day + ', ' + p.year;
  }

  function dateOnlyLabel(ymd) {
    var d = new Date(ymd + 'T12:00:00Z');
    return d.toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' });
  }

  function whenText(item) {
    if (item.event_start) {
      var text = dateLabel(item.event_start) + ', ' + timeLabel(item.event_start);
      return item.event_end ? text + ' to ' + timeLabel(item.event_end) : text;
    }
    if (item.deadline_at) return 'Due ' + dateLabel(item.deadline_at) + ', ' + timeLabel(item.deadline_at);
    if (item.deadline_date) return 'Due ' + dateOnlyLabel(item.deadline_date) + ' (all day)';
    return '';
  }

  // Short date for the card's top-right corner, in the page's "Deadline: Mon, Nov 16 • 4:00 PM" style.
  function cornerDate(item) {
    var p;
    if (item.deadline_at) {
      p = localParts(item.deadline_at);
      return 'Deadline: ' + p.weekday + ', ' + p.month + ' ' + p.day + ' • ' + timeLabel(item.deadline_at);
    }
    if (item.deadline_date) {
      var d = new Date(item.deadline_date + 'T12:00:00Z');
      return 'Deadline: ' + d.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric' });
    }
    if (item.event_start) {
      p = localParts(item.event_start);
      var range = timeLabel(item.event_start) + (item.event_end ? '–' + timeLabel(item.event_end) : '');
      return p.weekday + ', ' + p.month + ' ' + p.day + ' • ' + range;
    }
    return '';
  }

  // Day of November 2026 (campus time) for the page's own calendar grid, else null.
  function novemberDay(item) {
    var iso = item.event_start || item.deadline_at;
    if (iso) {
      var p = localParts(iso);
      return p.month === 'Nov' && p.year === '2026' ? parseInt(p.day, 10) : null;
    }
    if (item.deadline_date && item.deadline_date.indexOf('2026-11-') === 0) {
      return parseInt(item.deadline_date.slice(8, 10), 10);
    }
    return null;
  }

  function laneCounts(items) {
    var counts = { emergency: 0, urgent: 0, deadline: 0, general: 0 };
    items.forEach(function (i) { if (counts[i.priority] !== undefined) counts[i.priority] += 1; });
    return counts;
  }

  // What the corner shows instead of a bare number: emergencies are safety alerts,
  // and a 0 score is left out (the "Why" line already says there is no match).
  function scoreLabel(item) {
    if (item.priority === 'emergency') return 'Safety alert';
    if (!item.relevance_score) return '';
    return item.relevance_score + '/100 match';
  }

  var helpers = {
    apiBase: apiBase, addMinutesKeepOffset: addMinutesKeepOffset, nextDate: nextDate,
    calendarRequest: calendarRequest, googleCalendarUrl: googleCalendarUrl,
    whenText: whenText, cornerDate: cornerDate, novemberDay: novemberDay,
    laneCounts: laneCounts, scoreLabel: scoreLabel, PERSONA_PREFS: PERSONA_PREFS
  };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = helpers; // node tests
    return;
  }

  // ------------------------------------------------------------------ browser wiring

  var API = apiBase(window.location.search, window.AGGIE_API_BASE);
  var state = { token: null, items: [], container: null, persona: null };

  function toast(message) {
    if (typeof window.showToast === 'function') window.showToast(message);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function settle(status) {
    document.documentElement.dataset.aggieApi = status;
    document.documentElement.classList.remove('aggie-pending');
  }

  function networkError(err) {
    // fetch() rejects with a TypeError when the server can't be reached.
    throw err instanceof TypeError ? new Error(OFFLINE_MESSAGE) : err;
  }

  function readSession() {
    try {
      var saved = JSON.parse(window.sessionStorage.getItem('aggieconnect.session') || 'null');
      if (saved && saved.api === API && saved.expires > Date.now() + 60000) return saved.token;
    } catch (e) { /* storage unavailable */ }
    return null;
  }

  function writeSession(token, expiresIn) {
    try {
      window.sessionStorage.setItem('aggieconnect.session', JSON.stringify({
        api: API, token: token, expires: Date.now() + expiresIn * 1000
      }));
    } catch (e) { /* storage unavailable */ }
  }

  function newSession() {
    return fetch(API + '/demo/session', { method: 'POST' }).catch(networkError).then(function (res) {
      if (!res.ok) throw new Error('Could not start a demo session (' + res.status + ')');
      return res.json();
    }).then(function (body) {
      state.token = body.access_token;
      writeSession(body.access_token, body.expires_in || 3600);
      return state.token;
    });
  }

  function request(method, path, body, retried) {
    var headers = { Authorization: 'Bearer ' + state.token };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(API + path, {
      method: method, headers: headers, body: body === undefined ? undefined : JSON.stringify(body)
    }).catch(networkError).then(function (res) {
      if (res.status === 401 && !retried) {
        return newSession().then(function () { return request(method, path, body, true); });
      }
      if (res.status === 204) return null;
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var message = data && data.error && data.error.message ? data.error.message : 'Request failed (' + res.status + ')';
          throw new Error(message);
        }
        return data;
      });
    });
  }

  function currentPersona() {
    var forced = new URLSearchParams(window.location.search).get('persona');
    if (forced && PERSONA_PREFS[forced]) {
      var radio = document.getElementById('persona-' + forced);
      if (radio) radio.checked = true;
      return forced;
    }
    var checked = document.querySelector('input[name="student-persona"]:checked');
    var id = checked ? checked.id.replace('persona-', '') : 'cs';
    return PERSONA_PREFS[id] ? id : 'cs';
  }

  // ---------------------------------------------------------------- rendering

  function chip(text, cls) {
    return el('span', 'font-mono font-bold uppercase tracking-wider px-2 py-0.5 rounded-xs ' + cls, text);
  }

  function saveButton(item) {
    var btn = el('button', 'px-2.5 py-1 text-xs font-mono border border-slate-300 rounded-sm bg-white text-slate-700 hover:border-aggie-blue transition cursor-pointer' + TAP);
    btn.type = 'button';
    function paint() {
      btn.textContent = item.saved ? '★ Saved' : '☆ Save';
      btn.setAttribute('aria-pressed', item.saved ? 'true' : 'false');
      btn.classList.toggle('aggie-saved', !!item.saved);
    }
    paint();
    btn.addEventListener('click', function () {
      btn.disabled = true;
      var method = item.saved ? 'DELETE' : 'POST';
      request(method, '/opportunities/' + item.id + '/save').then(function () {
        item.saved = !item.saved;
        paint();
        toast(item.saved ? 'Saved "' + item.title + '".' : 'Removed "' + item.title + '" from saved.');
      }).catch(function (err) { toast(err.message); }).then(function () { btn.disabled = false; });
    });
    return btn;
  }

  function googleButton(item) {
    var url = googleCalendarUrl(item);
    if (!url) return null;
    var link = el('a', 'px-2.5 py-1 text-xs font-mono font-semibold border border-aggie-blue rounded-sm bg-aggie-blue text-white hover:bg-aggie-navy transition' + TAP, '+ Google Calendar');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.title = 'Opens Google Calendar with this event filled in. Review it and click Save.';
    link.addEventListener('click', function () {
      link.textContent = '↗ Opened in Google Calendar';
      toast('Review "' + item.title + '" in Google Calendar and click Save.');
    });
    return link;
  }

  function calendarButton(item) {
    var payload = calendarRequest(item);
    if (!payload) return null;
    var idle = 'Simulate Outlook add';
    var btn = el('button', 'font-mono text-xs font-semibold text-aggie-blue hover:underline cursor-pointer' + TAP);
    btn.type = 'button';
    btn.title = 'Demo mode: records a simulated Outlook calendar event (live Outlook needs NC A&T app approval).';
    if (item.calendar_status === 'added') {
      btn.textContent = '✓ Simulated in Outlook';
      btn.disabled = true;
      return btn;
    }
    var armed = false;
    btn.textContent = idle;
    btn.addEventListener('click', function () {
      if (!armed) { // two-step confirmation, as the API requires confirmed=true
        armed = true;
        btn.textContent = 'Confirm: ' + whenText(item) + '?';
        setTimeout(function () {
          if (armed && !btn.disabled) { armed = false; btn.textContent = idle; }
        }, 6000);
        return;
      }
      armed = false;
      btn.disabled = true;
      request('POST', '/calendar/events', payload).then(function (result) {
        item.calendar_status = 'added';
        btn.textContent = result && result.simulated ? '✓ Simulated in Outlook' : '✓ Added to Outlook';
        btn.className = 'font-mono text-xs font-semibold text-emerald-800 cursor-default' + TAP;
        var day = novemberDay(item);
        if (day && typeof window.syncEventToCalendar === 'function') {
          var time = item.event_start ? timeLabel(item.event_start)
            : item.deadline_at ? timeLabel(item.deadline_at) : 'All Day';
          window.syncEventToCalendar(null, day, item.title, time, item.location || 'See message', 'AI Email Deadline', 'ai');
        } else {
          toast('Added "' + item.title + '" to your calendar.');
        }
      }).catch(function (err) {
        btn.disabled = false;
        btn.textContent = idle;
        toast(err.message);
      });
    });
    return btn;
  }

  // Same structure and classes as the page's static digest cards.
  function card(item) {
    var lane = LANE_STYLE[item.priority] || LANE_STYLE.general;
    var article = el('article', 'feed-article aggie-lane-' + (LANE_STYLE[item.priority] ? item.priority : 'general'));
    article.dataset.opportunityId = item.id;
    var content = el('div', 'digest-content min-w-0');

    var top = el('div', 'flex flex-wrap items-center justify-between gap-2 text-xs mb-1.5');
    var tags = el('div', 'flex flex-wrap items-center gap-2');
    tags.appendChild(chip(lane.label, lane.chip));
    tags.appendChild(el('span', 'font-mono font-medium text-aggie-blue bg-blue-50 px-2 py-0.5 rounded-xs capitalize', item.category));
    if (item.needs_review) tags.appendChild(chip('Needs review', 'text-amber-900 bg-amber-100 border-l-2 border-amber-600'));
    top.appendChild(tags);

    var corner = el('div', 'flex flex-wrap items-center gap-x-3 gap-y-1');
    var when = cornerDate(item);
    if (when) corner.appendChild(el('span', 'font-mono font-semibold ' + lane.time, when));
    var score = scoreLabel(item);
    if (score) {
      corner.appendChild(el('span', 'font-mono font-bold ' + (item.priority === 'emergency' ? 'text-red-800' : 'text-aggie-blue'), score));
    }
    if (corner.childNodes.length) top.appendChild(corner);
    content.appendChild(top);

    content.appendChild(el('h3', 'digest-title font-serif text-xl sm:text-2xl font-bold text-aggie-navy leading-snug', item.title));
    if (item.summary) content.appendChild(el('p', 'text-[15px] text-slate-700 mt-2 leading-relaxed', item.summary));
    content.appendChild(el('p', 'font-mono text-xs text-aggie-blue mt-2', 'Why: ' + item.relevance_reason));
    if (item.location) content.appendChild(el('p', 'font-mono text-xs text-slate-500 mt-1', 'Location: ' + item.location));

    var actions = el('div', 'mt-4 flex flex-wrap items-center gap-3');
    actions.appendChild(saveButton(item));
    var google = googleButton(item);
    if (google) actions.appendChild(google);
    var cal = calendarButton(item);
    if (cal) actions.appendChild(cal);
    content.appendChild(actions);

    article.appendChild(content);
    return article;
  }

  function setStatus(text) {
    var badge = document.getElementById('digest-status');
    if (badge && badge.lastChild) badge.lastChild.textContent = ' ' + text;
  }

  function setSubtitle(text) {
    var sub = document.getElementById('digest-subtitle');
    if (sub) sub.textContent = text;
  }

  function updateHeader(items) {
    var counts = laneCounts(items);
    var nav = document.getElementById('nav-digest-count');
    if (nav) nav.textContent = String(items.length);

    var chips = document.querySelector('#view-home details summary span.flex');
    if (chips) {
      chips.textContent = '';
      chips.appendChild(el('strong', 'text-aggie-navy uppercase tracking-wider', 'Ranked lanes:'));
      LANE_ORDER.forEach(function (key) {
        // Empty lanes stay listed (so the order is clear) but are dimmed.
        var span = el('span', 'px-2 py-0.5 rounded-xs font-bold ' + LANE_STYLE[key].chip + (counts[key] ? '' : ' opacity-40'),
          counts[key] + ' ' + LANE_STYLE[key].label);
        chips.appendChild(span);
      });
    }

    var breakdown = document.querySelector('#view-home details > div');
    if (breakdown) {
      breakdown.textContent = '';
      [
        'Verified emergencies come first, then urgent, action-needed and opportunity items.',
        'Within a lane, items are ordered by match score: interest 35, major 25, career goal 20, academic level 10, organization 10.',
        counts.emergency + counts.urgent + counts.deadline + ' items need action; ' +
          items.filter(function (i) { return i.needs_review; }).length + ' are flagged for review.'
      ].forEach(function (line) { breakdown.appendChild(el('span', null, '• ' + line)); });
    }

    setStatus('Live • ' + items.length + ' sample emails ranked by AggieConnect (demo mode)');
    setSubtitle('Synthetic demo inbox: each announcement is classified by AggieConnect and ranked against your preferences. Switch students in the sidebar to see the ranking change.');
  }

  function render() {
    var c = state.container;
    c.textContent = '';
    state.items.forEach(function (item) { c.appendChild(card(item)); });
    updateHeader(state.items);
  }

  // ---------------------------------------------------------------- actions

  function loadFeed() {
    return request('GET', '/opportunities?limit=50').then(function (data) {
      state.items = data.items || [];
      render();
    });
  }

  function applyPersona(announce) {
    state.persona = currentPersona();
    return request('PUT', '/me/preferences', PERSONA_PREFS[state.persona]).then(loadFeed).then(function () {
      if (announce) toast('Feed re-ranked for ' + PERSONA_PREFS[state.persona].major + '.');
    });
  }

  function addRefreshButton() {
    var header = document.querySelector('#view-home .pb-6 > div');
    if (!header || document.getElementById('aggie-refresh')) return;
    var btn = el('button', 'font-mono text-[11px] font-semibold text-aggie-blue border border-aggie-blue/40 bg-white px-2.5 py-0.5 rounded-full hover:bg-blue-50 cursor-pointer self-start' + TAP, '↻ Refresh inbox');
    btn.id = 'aggie-refresh';
    btn.type = 'button';
    btn.addEventListener('click', function () {
      btn.disabled = true;
      request('POST', '/sync').then(function (counts) {
        toast('Inbox refreshed: ' + counts.fetched + ' fetched, ' + counts.imported + ' new, ' + counts.unchanged + ' unchanged.');
        return loadFeed();
      }).catch(function (err) { toast(err.message); }).then(function () { btn.disabled = false; });
    });
    header.appendChild(btn);
  }

  function start() {
    state.container = document.querySelector('#view-home > .mt-1');
    if (!state.container) { settle('offline'); return; }
    state.token = readSession();
    (state.token ? Promise.resolve(state.token) : newSession())
      .then(function () { return applyPersona(false); })
      .then(function () {
        addRefreshButton();
        settle('connected');
        document.querySelectorAll('input[name="student-persona"]').forEach(function (radio) {
          radio.addEventListener('change', function () {
            applyPersona(true).catch(function (err) { toast(err.message); });
          });
        });
      })
      .catch(function () {
        settle('offline');
        setStatus('Sample digest • AggieConnect is offline');
        setSubtitle("Showing sample content because AggieConnect can't be reached right now. Live rankings return when it's back.");
        toast("Can't reach AggieConnect right now. Showing a sample digest.");
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
