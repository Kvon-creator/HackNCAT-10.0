/*
 * "+ Google Calendar" links for the page's own events (works with or without the API):
 *   - every announcement / sample digest item that has a "Sync ... Calendar" button
 *   - every event listed in the calendar's "Selected date focus" and upcoming agenda
 *
 * Opens Google Calendar with the event filled in; the student reviews it and clicks Save.
 * Existing functions are not modified: event details are read from the existing
 * syncEventToCalendar(...) buttons and from calendarEvents after each agenda render.
 * All dates are November 2026, campus time (America/New_York).
 */
(function () {
  'use strict';

  var ZONE = 'America/New_York';
  var YEAR = 2026;
  var MONTH = 11;
  var DURATION_MIN = 60;
  var LINK_CLASS = 'aggie-gcal';

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  // "3:00 PM" -> { h: 15, m: 0 }; "All Day" or anything else -> null (all-day event)
  function parseTime(text) {
    var m = /^(\d{1,2}):(\d{2})\s*([AP])\.?M\.?$/i.exec(String(text || '').trim());
    if (!m) return null;
    var h = parseInt(m[1], 10) % 12 + (m[3].toUpperCase() === 'P' ? 12 : 0);
    return { h: h, m: parseInt(m[2], 10) };
  }

  // Wall-clock stamp YYYYMMDDTHHMMSS; Google reads it in the ctz time zone.
  function wallStamp(date) {
    return date.getUTCFullYear() + pad(date.getUTCMonth() + 1) + pad(date.getUTCDate()) +
      'T' + pad(date.getUTCHours()) + pad(date.getUTCMinutes()) + '00';
  }

  function dayStamp(date) {
    return date.getUTCFullYear() + pad(date.getUTCMonth() + 1) + pad(date.getUTCDate());
  }

  // ev: { day, title, time, location, details }
  function eventUrl(ev) {
    var day = parseInt(ev.day, 10);
    if (!day) return null;
    var t = parseTime(ev.time);
    var dates;
    if (t) {
      var start = new Date(Date.UTC(YEAR, MONTH - 1, day, t.h, t.m));
      var end = new Date(start.getTime() + DURATION_MIN * 60000);
      dates = wallStamp(start) + '/' + wallStamp(end);
    } else {
      dates = dayStamp(new Date(Date.UTC(YEAR, MONTH - 1, day))) + '/' + dayStamp(new Date(Date.UTC(YEAR, MONTH - 1, day + 1)));
    }
    var params = new URLSearchParams({
      action: 'TEMPLATE', text: ev.title || 'Aggie Dispatch event', dates: dates, ctz: ZONE,
      details: [ev.details, 'Added from Aggie Dispatch.'].filter(Boolean).join('\n\n').slice(0, 1200)
    });
    if (ev.location) params.set('location', ev.location);
    return 'https://calendar.google.com/calendar/render?' + params.toString();
  }

  // Reads the arguments of an existing onclick="syncEventToCalendar(this, 16, 'Title', '2:00 PM', 'Place', ...)"
  function parseSyncCall(onclick) {
    var q = "'((?:[^'\\\\]|\\\\.)*)'";
    var m = new RegExp('syncEventToCalendar\\(\\s*this\\s*,\\s*(\\d+)\\s*,\\s*' + q + '\\s*,\\s*' + q + '\\s*,\\s*' + q).exec(onclick || '');
    if (!m) return null;
    var unescape = function (s) { return s.replace(/\\(.)/g, '$1'); };
    return { day: parseInt(m[1], 10), title: unescape(m[2]), time: unescape(m[3]), location: unescape(m[4]) };
  }

  var api = { parseTime: parseTime, eventUrl: eventUrl, parseSyncCall: parseSyncCall };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  // ------------------------------------------------------------------ browser wiring

  function makeLink(ev, extraClass) {
    var url = eventUrl(ev);
    if (!url) return null;
    var a = document.createElement('a');
    a.className = LINK_CLASS + ' font-mono text-xs font-semibold text-aggie-blue hover:text-aggie-navy underline underline-offset-4 ' +
      'decoration-aggie-blue/40 whitespace-nowrap min-h-[44px] sm:min-h-0 inline-flex items-center ' + (extraClass || '');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = '+ Google Calendar';
    a.title = 'Opens Google Calendar with "' + ev.title + '" filled in. Review it and click Save.';
    a.setAttribute('aria-label', 'Add "' + ev.title + '" to Google Calendar');
    a.addEventListener('click', function () {
      if (typeof window.showToast === 'function') window.showToast('Review "' + ev.title + '" in Google Calendar and click Save.');
    });
    return a;
  }

  // Announcements and sample digest items: add a link beside each "Sync ... Calendar" button.
  function linkSyncButtons(root) {
    (root || document).querySelectorAll('button[onclick*="syncEventToCalendar(this"]').forEach(function (btn) {
      if (btn.dataset.gcalLinked) return;
      var ev = parseSyncCall(btn.getAttribute('onclick'));
      if (!ev) return;
      var article = btn.closest('article');
      if (article) {
        var heading = article.querySelector('h3');
        var para = article.querySelector('h3 + p');
        ev.details = [heading && heading.textContent.trim(), para && para.textContent.trim()].filter(Boolean).join('\n\n');
      }
      var link = makeLink(ev);
      if (!link) return;
      btn.dataset.gcalLinked = '1';
      btn.insertAdjacentElement('afterend', link);
      // keep the pair together when the action row wraps
      if (btn.parentElement) btn.parentElement.classList.add('gap-3');
    });
  }

  // Calendar agenda lists: append a link to each rendered event, using the same data the list was built from.
  function linkAgendaItems(listId, events) {
    var list = document.getElementById(listId);
    if (!list) return;
    var items = list.querySelectorAll(':scope > li');
    events.forEach(function (ev, i) {
      var li = items[i];
      if (!li || li.querySelector('.' + LINK_CLASS)) return;
      var link = makeLink({ day: ev.day, title: ev.title, time: ev.time, location: ev.location, details: ev.source });
      if (!link) return;
      var timeEl = li.lastElementChild;
      var wrap = document.createElement('div');
      wrap.className = 'flex items-center gap-3 shrink-0 sm:justify-end';
      li.replaceChild(wrap, timeEl);
      wrap.appendChild(timeEl);
      wrap.appendChild(link);
    });
  }

  function dayEvents(day) {
    var all = (typeof calendarEvents !== 'undefined' && calendarEvents[day]) || [];
    return all.map(function (ev) { return Object.assign({ day: day }, ev); });
  }

  function upcomingEvents() {
    if (typeof calendarEvents === 'undefined') return [];
    // same selection and order as renderUpcomingAgenda()
    return Object.keys(calendarEvents).map(Number).filter(function (d) { return d >= 14; })
      .sort(function (a, b) { return a - b; })
      .reduce(function (acc, d) { return acc.concat(dayEvents(d)); }, []);
  }

  function wrapRenderer(name, after) {
    var original = window[name];
    if (typeof original !== 'function' || original.gcalWrapped) return;
    var wrapped = function () {
      var result = original.apply(this, arguments);
      try { after.apply(null, arguments); } catch (e) { /* links are an enhancement only */ }
      return result;
    };
    wrapped.gcalWrapped = true;
    window[name] = wrapped;
  }

  wrapRenderer('renderDayAgenda', function (day) { linkAgendaItems('agenda-items-list', dayEvents(day)); });
  wrapRenderer('renderUpcomingAgenda', function () { linkAgendaItems('upcoming-agenda-list', upcomingEvents()); });

  function start() {
    linkSyncButtons(document);
    // Agenda lists may already be rendered (DOMContentLoaded order); link what's there now too.
    var title = document.getElementById('agenda-date-title');
    var m = title && /November (\d+)/.exec(title.textContent);
    if (m) linkAgendaItems('agenda-items-list', dayEvents(parseInt(m[1], 10)));
    linkAgendaItems('upcoming-agenda-list', upcomingEvents());
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
