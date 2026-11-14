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
    general: { label: 'General', chip: 'text-aggie-blue bg-blue-100', time: 'text-slate-500' }
  };
  // In the general lane, real opportunities are labeled as such; newsletters, scams and unrelated mail are not.
  var OPPORTUNITY_CATEGORIES = { internship: 1, scholarship: 1, research: 1, event: 1 };
  function laneChipLabel(item) {
    var lane = LANE_STYLE[item.priority] || LANE_STYLE.general;
    if (lane === LANE_STYLE.general && OPPORTUNITY_CATEGORIES[item.category]) return 'Opportunity';
    return lane.label;
  }
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
  // lane: null = show everything (default); otherwise one of LANE_ORDER
  var state = { token: null, items: [], container: null, persona: null, lane: null };

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
  // opts.preview: a classified-on-the-spot result (not in the feed): no Save or Outlook actions.
  function card(item, opts) {
    var preview = !!(opts && opts.preview);
    var lane = LANE_STYLE[item.priority] || LANE_STYLE.general;
    var article = el('article', 'feed-article aggie-lane-' + (LANE_STYLE[item.priority] ? item.priority : 'general'));
    if (!preview) article.dataset.opportunityId = item.id;
    var content = el('div', 'digest-content min-w-0');

    var top = el('div', 'flex flex-wrap items-center justify-between gap-2 text-xs mb-1.5');
    var tags = el('div', 'flex flex-wrap items-center gap-2');
    tags.appendChild(chip(laneChipLabel(item), lane.chip));
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
    if (!preview) actions.appendChild(saveButton(item));
    var google = googleButton(item);
    if (google) actions.appendChild(google);
    var cal = preview ? null : calendarButton(item);
    if (cal) actions.appendChild(cal);
    if (actions.childNodes.length) content.appendChild(actions);

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

    // The collapsible strip now only explains the ranking; the lane chips become filter buttons below it.
    var chips = document.querySelector('#view-home details summary span.flex');
    if (chips) {
      chips.classList.add('flex-1', 'min-w-0');
      chips.textContent = '';
      chips.appendChild(el('strong', 'text-aggie-navy uppercase tracking-wider', 'How this digest is ranked'));
    }
    var toggle = document.querySelector('#view-home details summary > span:last-child');
    if (toggle && toggle.lastChild) toggle.lastChild.textContent = ' Details';
    renderLaneFilter(counts, items.length);

    var breakdown = document.querySelector('#view-home details > div');
    if (breakdown) {
      breakdown.textContent = '';
      [
        'Verified emergencies come first, then urgent, action-needed and general items.',
        'Within a lane, items are ordered by match score: interest 35, major 25, career goal 20, academic level 10, organization 10.',
        counts.emergency + counts.urgent + counts.deadline + ' items need action; ' +
          items.filter(function (i) { return i.needs_review; }).length + ' are flagged for review.'
      ].forEach(function (line) { breakdown.appendChild(el('span', null, '• ' + line)); });
    }

    setStatus('Live • ' + items.length + ' sample emails ranked by AggieConnect (demo mode)');
    setSubtitle('Synthetic demo inbox: each announcement is classified by AggieConnect and ranked against your preferences. Switch students in the sidebar to see the ranking change.');
  }

  function filterButton(lane, text, cls, empty) {
    var active = state.lane === lane;
    var b = el('button', 'px-2.5 py-1 rounded-xs font-mono text-xs font-bold transition ' + cls +
      (empty ? ' opacity-40 cursor-not-allowed' : ' cursor-pointer hover:opacity-90') + (active ? ' aggie-filter-active' : '') + TAP, text);
    b.type = 'button';
    b.dataset.lane = lane || 'all';
    b.setAttribute('aria-pressed', active ? 'true' : 'false');
    if (empty) { b.disabled = true; b.title = 'No messages in this lane'; }
    b.addEventListener('click', function () {
      // Clicking the active lane (or "All") returns to the default, unfiltered digest.
      state.lane = lane === null || state.lane === lane ? null : lane;
      render();
      var again = document.querySelector('#aggie-lane-filter [data-lane="' + (lane || 'all') + '"]');
      if (again) again.focus();
    });
    return b;
  }

  function renderLaneFilter(counts, total) {
    var bar = document.getElementById('aggie-lane-filter');
    if (!bar) {
      var strip = document.querySelector('#view-home .pb-6 > details');
      if (!strip) return;
      bar = el('div', 'mt-3 flex flex-wrap items-center gap-2');
      bar.id = 'aggie-lane-filter';
      bar.setAttribute('role', 'group');
      bar.setAttribute('aria-label', 'Filter the digest by lane');
      strip.insertAdjacentElement('afterend', bar);
    }
    bar.textContent = '';
    bar.appendChild(el('span', 'font-mono text-xs font-bold uppercase tracking-wider text-aggie-navy mr-1', 'Show:'));
    bar.appendChild(filterButton(null, 'All ' + total, 'text-aggie-navy bg-white border border-slate-300'));
    LANE_ORDER.forEach(function (key) {
      bar.appendChild(filterButton(key, counts[key] + ' ' + LANE_STYLE[key].label, LANE_STYLE[key].chip, !counts[key]));
    });
  }

  function visibleItems() {
    return state.lane ? state.items.filter(function (i) { return i.priority === state.lane; }) : state.items;
  }

  function render() {
    var c = state.container;
    c.textContent = '';
    var shown = visibleItems();
    shown.forEach(function (item) { c.appendChild(card(item)); });
    if (!shown.length && state.items.length) {
      var empty = el('div', 'py-10 font-mono text-sm text-slate-600');
      empty.appendChild(document.createTextNode('No messages in this lane right now. '));
      var reset = el('button', 'font-semibold text-aggie-blue underline underline-offset-4 cursor-pointer' + TAP, 'Show all messages');
      reset.type = 'button';
      reset.addEventListener('click', function () { state.lane = null; render(); });
      empty.appendChild(reset);
      c.appendChild(empty);
    }
    updateHeader(state.items);
    if (state.lane) {
      setStatus('Showing ' + shown.length + ' of ' + state.items.length + ' • ' + LANE_STYLE[state.lane].label + ' only');
    }
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

  // "Try any announcement": classify pasted text live via POST /api/classify (nothing is stored).
  var TRY_SAMPLES = {
    phishing: {
      subject: 'URGENT: Your student account will be locked',
      body: 'Final notice! Your Aggie account will be locked today. Verify your password within 24 hours at the link below to keep access.'
    },
    event: {
      subject: 'Robotics Club info session',
      body: 'Join the Robotics Club for an info session on December 3, 2026, 5:30-6:30 p.m. Eastern in McNair Hall, Room 210. All Computer Science majors welcome.'
    }
  };

  function field(id, labelText, input) {
    var wrap = el('div', 'flex flex-col gap-1.5');
    var label = el('label', 'font-mono text-xs font-semibold uppercase tracking-wider text-slate-600', labelText);
    label.htmlFor = id;
    input.id = id;
    input.className = 'w-full min-h-[44px] px-3 py-2 bg-white border border-slate-300 rounded-sm text-[15px] text-aggie-ink focus:outline-none focus:border-aggie-blue';
    wrap.appendChild(label);
    wrap.appendChild(input);
    return wrap;
  }

  function renderTryResult(box, data) {
    box.textContent = '';
    var meta = el('p', 'font-mono text-xs text-slate-600 mt-5',
      'Classified just now by: ' + data.classified_by + ' · not saved to your feed');
    box.appendChild(meta);
    if (data.safety_notes && data.safety_notes.length) {
      var notes = el('ul', 'mt-3 space-y-1.5 border-l-4 border-amber-600 bg-amber-50 px-4 py-3 text-sm text-amber-950 list-none');
      notes.setAttribute('aria-label', 'Safety checks');
      data.safety_notes.forEach(function (note) { notes.appendChild(el('li', null, '⚠ ' + note)); });
      box.appendChild(notes);
    }
    box.appendChild(card(data, { preview: true }));
  }

  function addTryPanel() {
    if (document.getElementById('aggie-try') || !state.container) return;
    var panel = el('details', 'mt-6 bg-white border border-slate-300 rounded-md px-4 py-3');
    panel.id = 'aggie-try';
    var summary = el('summary', 'flex flex-wrap items-center justify-between gap-2 font-mono text-xs text-slate-700 select-none min-h-[44px] sm:min-h-0');
    var label = el('span', 'flex flex-wrap items-center gap-2');
    label.appendChild(el('strong', 'text-aggie-navy uppercase tracking-wider', '✎ Try any announcement'));
    label.appendChild(el('span', 'text-slate-600', 'Paste an email and watch it get classified live'));
    summary.appendChild(label);
    var chevron = el('span', 'text-aggie-blue font-semibold inline-flex items-center gap-1');
    chevron.appendChild(el('span', 'chevron-arrow inline-block transition-transform', '▸'));
    chevron.appendChild(document.createTextNode(' Open'));
    summary.appendChild(chevron);
    panel.appendChild(summary);

    var form = el('form', 'mt-4 flex flex-col gap-3');
    var subject = document.createElement('input');
    subject.type = 'text';
    subject.maxLength = 300;
    subject.placeholder = 'e.g., Research positions open in the Robotics Lab';
    var body = document.createElement('textarea');
    body.rows = 4;
    body.maxLength = 5000;
    body.placeholder = 'Paste or type the message text, including any dates, times and locations.';
    form.appendChild(field('aggie-try-subject', 'Subject', subject));
    form.appendChild(field('aggie-try-body', 'Message', body));

    var row = el('div', 'flex flex-wrap items-center gap-3');
    var submit = el('button', 'px-4 py-2 text-xs font-semibold uppercase tracking-wider bg-aggie-blue hover:bg-aggie-navy text-white rounded-sm cursor-pointer' + TAP, 'Classify');
    submit.type = 'submit';
    row.appendChild(submit);
    row.appendChild(el('span', 'font-mono text-xs text-slate-500', 'Samples:'));
    [['phishing', 'Phishing email'], ['event', 'Event invite']].forEach(function (pair) {
      var b = el('button', 'px-2.5 py-1 text-xs font-mono border border-slate-300 rounded-sm bg-white text-slate-700 hover:border-aggie-blue cursor-pointer' + TAP, pair[1]);
      b.type = 'button';
      b.addEventListener('click', function () {
        subject.value = TRY_SAMPLES[pair[0]].subject;
        body.value = TRY_SAMPLES[pair[0]].body;
        body.focus();
      });
      row.appendChild(b);
    });
    form.appendChild(row);

    var result = el('div', '');
    result.setAttribute('aria-live', 'polite');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!subject.value.trim() && !body.value.trim()) { body.focus(); return; }
      submit.disabled = true;
      submit.textContent = 'Classifying…';
      request('POST', '/classify', { subject: subject.value, body: body.value }).then(function (data) {
        renderTryResult(result, data);
      }).catch(function (err) {
        result.textContent = '';
        result.appendChild(el('p', 'mt-4 text-sm text-red-800', err.message));
      }).then(function () {
        submit.disabled = false;
        submit.textContent = 'Classify';
      });
    });

    panel.appendChild(form);
    panel.appendChild(result);
    state.container.insertAdjacentElement('beforebegin', panel);
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
        addTryPanel();
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
