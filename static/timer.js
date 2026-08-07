/* ==========================================================================
   timer.js — the ticking half of the board.
   Every element carrying data-deadline gets a live countdown; the masthead
   gets a wall clock. One interval drives all of it.
   ========================================================================== */

(function (global) {
  "use strict";

  var SECOND = 1000;
  var MINUTE = 60 * SECOND;
  var HOUR = 60 * MINUTE;
  var DAY = 24 * HOUR;

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  /** "3d 04h" / "04h 12m" / "12:34" — the largest two units that still matter. */
  function span(ms) {
    if (ms >= DAY) {
      return Math.floor(ms / DAY) + "d " + pad(Math.floor((ms % DAY) / HOUR)) + "h";
    }
    if (ms >= HOUR) {
      return pad(Math.floor(ms / HOUR)) + "h " + pad(Math.floor((ms % HOUR) / MINUTE)) + "m";
    }
    return pad(Math.floor(ms / MINUTE)) + ":" + pad(Math.floor((ms % MINUTE) / SECOND));
  }

  /**
   * @returns {{text: string, state: "none"|"done"|"overdue"|"soon"|"ok"}}
   */
  function countdown(deadline, status) {
    if (status === "done") return { text: "DONE", state: "done" };
    if (!deadline) return { text: "NO DATE", state: "none" };

    var target = new Date(deadline).getTime();
    if (isNaN(target)) return { text: "NO DATE", state: "none" };

    var diff = target - Date.now();
    if (diff <= 0) return { text: "\u2212" + span(-diff), state: "overdue" };
    return { text: span(diff), state: diff < DAY ? "soon" : "ok" };
  }

  /** Local date + time, e.g. "12 Aug 17:00". */
  function formatDeadline(deadline) {
    if (!deadline) return { date: "—", time: "" };
    var d = new Date(deadline);
    if (isNaN(d.getTime())) return { date: "—", time: "" };
    return {
      date: d.toLocaleDateString(undefined, { day: "2-digit", month: "short" }),
      time: pad(d.getHours()) + ":" + pad(d.getMinutes())
    };
  }

  /** Fill a datetime-local input from an ISO string. */
  function toInputValue(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      "T" + pad(d.getHours()) + ":" + pad(d.getMinutes())
    );
  }

  /** Read a datetime-local input back out as UTC ISO (what the API stores). */
  function fromInputValue(value) {
    if (!value) return null;
    var d = new Date(value);
    return isNaN(d.getTime()) ? null : d.toISOString();
  }

  function paint(root) {
    var scope = root || document;
    var cells = scope.querySelectorAll("[data-deadline]");
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i];
      var value = cell.getAttribute("data-deadline");
      var result = countdown(value === "" ? null : value, cell.getAttribute("data-status"));
      if (cell.textContent !== result.text) cell.textContent = result.text;
      if (cell.getAttribute("data-state") !== result.state) {
        cell.setAttribute("data-state", result.state);
      }
    }

    var clock = document.getElementById("wall-clock");
    if (clock) {
      var now = new Date();
      clock.textContent = pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
    }
  }

  var ticking = null;

  function start() {
    paint();
    if (ticking === null) ticking = setInterval(function () { paint(); }, SECOND);
  }

  function stop() {
    clearInterval(ticking);
    ticking = null;
  }

  global.TaskTimer = {
    countdown: countdown,
    formatDeadline: formatDeadline,
    toInputValue: toInputValue,
    fromInputValue: fromInputValue,
    paint: paint,
    start: start,
    stop: stop
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})(window);
