"use strict";
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
              "Saturday", "Sunday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];
const base = location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8000";
const token = new URLSearchParams(location.search).get("token") || "";
const state = { instance: null, health: null, check: null, solved: null,
                schema: null, draft: null, dropped: null, dirty: false,
                memo: false, memoText: "", read: null, readError: "",
                seconds: 30, seed: 0, busy: false, step: "period",
                view: { find: "", role: "", only: false }, lit: "", who: "",
                edit: null, gone: null, staffFind: "", pick: "", pickFind: "" };
const at = id => document.getElementById(id);
const panel = name => document.querySelector('[data-fill="' + name + '"]');

function esc(value) {
  return String(value).replace(/[&<>"]/g, ch =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
}

function say(head, tail, tone) {
  at("tick").textContent = head;
  at("tock").textContent = tail || "";
  at("ticker").dataset.tone = tone || "";
}

async function api(path, payload) {
  const head = {};
  if (token) head["Authorization"] = "Bearer " + token;
  if (payload !== undefined) head["Content-Type"] = "application/json";
  let reply;
  try {
    reply = await fetch(base + path, {
      method: payload === undefined ? "GET" : "POST",
      headers: head,
      body: payload === undefined ? undefined : JSON.stringify(payload)
    });
  } catch (err) {
    throw new Error("the engine is not answering — start it with: " +
                    "python -m roster.cli serve");
  }
  const text = await reply.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (err) { data = null; }
  if (reply.status === 401) {
    throw new Error("the engine wants a token — open this page with " +
                    "?token=… on the end of the address");
  }
  if (!reply.ok) {
    const why = (data && data.error) || reply.status + " " + reply.statusText;
    throw new Error(data && data.field ? why + " (" + data.field + ")" : why);
  }
  return data;
}
function isoDate(iso) { return new Date(iso + "T00:00:00"); }

function longDate(iso) {
  const day = isoDate(iso);
  return DAYS[(day.getDay() + 6) % 7].slice(0, 3) + " " + day.getDate() + " " +
         MONTHS[day.getMonth()] + " " + day.getFullYear();
}

function addDays(iso, count) {
  const day = isoDate(iso);
  day.setDate(day.getDate() + count);
  return [day.getFullYear(),
          String(day.getMonth() + 1).padStart(2, "0"),
          String(day.getDate()).padStart(2, "0")].join("-");
}

function clock(minutes) {
  const inDay = ((minutes % 1440) + 1440) % 1440;
  return String(Math.floor(inDay / 60)).padStart(2, "0") + ":" +
         String(inDay % 60).padStart(2, "0");
}

function hours(minutes) {
  return (minutes % 60 ? (minutes / 60).toFixed(1) : minutes / 60) + "h";
}

function daysBetween(from, to) {
  return Math.round((isoDate(to) - isoDate(from)) / 86400000);
}

function weekdayOf(iso) { return (isoDate(iso).getDay() + 6) % 7; }

function realDate(iso) {
  return /^\d{4}-\d\d-\d\d$/.test(String(iso || "")) &&
         !isNaN(isoDate(iso).getDate());
}

function parseClock(text) {
  const parts = String(text || "").split(":");
  const hour = parseInt(parts[0], 10);
  const minute = parseInt(parts[1] || "0", 10);
  if (!isFinite(hour) || !isFinite(minute)) return null;
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
  return hour * 60 + minute;
}

function ledger(rows) {
  return '<dl class="ledger">' + rows.map(row =>
    "<dt" + (row[2] ? ' class="' + row[2] + '"' : "") + ">" + esc(row[0]) +
    "</dt><dd>" + esc(row[1]) + "</dd>").join("") + "</dl>";
}

function tally(rows) {
  return '<ul class="tally">' + rows.map(row =>
    "<li><b>" + esc(row[1]) + "</b>" + esc(row[0]) + "</li>").join("") + "</ul>";
}

function num(value) {
  return value % 1 ? value.toFixed(1) : String(value);
}

function press(label, action, quiet, off, id) {
  return '<button class="' + (quiet ? "quiet" : "act") + '" type="button" ' +
         'data-do="' + action + '"' + (id ? ' data-id="' + esc(id) + '"' : "") +
         (off ? " disabled" : "") + ">" + esc(label) + "</button>";
}

function nothingYet(message, label, action) {
  return '<div class="empty"><p>' + esc(message) + "</p>" +
         press(label, action) + "</div>";
}
const OPEN_IT = "Open the sample month";
const HINT = "Point at any duty and it is read out here.";

function datedParams(type) {
  const card = typeCard(type);
  return (card ? card.params : []).filter(param =>
    param.kind === "day" || param.kind === "days");
}

function demandByDay(inst) {
  const byDay = {};
  inst.demand.forEach(line => {
    (byDay[line.day] || (byDay[line.day] = [])).push(line);
  });
  return byDay;
}

function shapeKey(lines) {
  return (lines || []).map(line =>
    line.shift + "/" + line.role + "/" + line.required).sort().join(",");
}

function twoShapes(inst) {
  const byDay = demandByDay(inst);
  const resting = restDays(inst);
  const found = { working: null, weekend: null };
  for (let day = 0; day < inst.horizon.num_days; day += 1) {
    const kind = resting(addDays(inst.horizon.start, day)) ? "weekend" : "working";
    const lines = byDay[day] || [];
    if (found[kind] === null) found[kind] = lines;
    else if (shapeKey(found[kind]) !== shapeKey(lines)) return null;
  }
  return found.working && found.weekend ? found : null;
}

function remapDemand(inst, span) {
  const shapes = twoShapes(inst);
  const resting = restDays({ horizon: span });
  const byDay = demandByDay(inst);
  const out = [];
  const copy = (day, lines) => (lines || []).forEach(line => out.push({
    day: day, shift: line.shift, role: line.role, required: line.required }));
  for (let day = 0; day < span.num_days; day += 1) {
    if (shapes) {
      copy(day, shapes[resting(addDays(span.start, day)) ? "weekend" : "working"]);
    } else {
      let from = day;
      while (from >= inst.horizon.num_days && from >= 7) from -= 7;
      copy(day, byDay[from]);
    }
  }
  return { demand: out, laid: Boolean(shapes),
           how: shapes ? "the weekday and weekend levels follow the new calendar"
                       : "each added day repeats the same weekday a week earlier" };
}

function moveRules(inst, delta, span) {
  const kept = [], lost = [], moved = [];
  let trimmed = 0;
  const inside = iso => {
    const off = daysBetween(span.start, iso);
    return off >= 0 && off < span.num_days;
  };
  inst.rules.forEach(rule => {
    const dated = datedParams(rule.type).filter(param =>
      !blank((rule.params || {})[param.name]));
    if (!dated.length) { kept.push(rule); return; }
    const params = Object.assign({}, rule.params);
    let gone = false;
    dated.forEach(param => {
      const value = params[param.name];
      if (param.kind === "day") {
        const to = addDays(value, delta);
        if (inside(to)) params[param.name] = to; else gone = true;
        return;
      }
      const all = value.map(iso => addDays(iso, delta));
      const held = all.filter(inside);
      if (!held.length) { gone = true; return; }
      if (held.length < all.length) trimmed += 1;
      params[param.name] = held;
    });
    if (gone) { lost.push(rule); return; }
    moved.push(rule);
    kept.push(Object.assign({}, rule, { params: params }));
  });
  return { rules: kept, lost: lost, moved: moved, trimmed: trimmed };
}

function periodTrial() {
  const edit = state.edit;
  const inst = state.instance;
  if (!edit || !inst) return null;
  const days = parseInt(edit.days, 10);
  if (!realDate(edit.start) || !isFinite(days) || days < 1 || days > 62) return null;
  const span = Object.assign({}, inst.horizon,
                             { start: edit.start, num_days: days });
  return { span: span, delta: daysBetween(inst.horizon.start, edit.start),
           rules: moveRules(inst, daysBetween(inst.horizon.start, edit.start), span),
           demand: remapDemand(inst, span) };
}

function periodWords(trial) {
  const was = state.instance.horizon;
  const span = trial.span;
  const rows = [
    ["Would run", longDate(span.start) + " to " +
                  longDate(addDays(span.start, span.num_days - 1))],
    ["First day", trial.delta === 0 ? "unchanged"
      : Math.abs(trial.delta) + " day" + (Math.abs(trial.delta) === 1 ? "" : "s") +
        " " + (trial.delta > 0 ? "later" : "earlier")],
    ["Length", span.num_days === was.num_days ? "unchanged at " + was.num_days + " days"
      : was.num_days + " days becomes " + span.num_days],
    ["Demand", trial.demand.demand.length + " lines — " + trial.demand.how]
  ];
  const moved = trial.rules.moved.length;
  rows.push(["Dated rules", moved
    ? moved + " move with the month" +
      (trial.rules.trimmed ? ", " + trial.rules.trimmed + " trimmed to fit" : "")
    : "none of them carry a date"]);
  if (trial.rules.lost.length) rows.push(["Would be dropped",
    trial.rules.lost.map(rule => rule.label).join("; "), "bad"]);
  return rows;
}

function periodSlip() {
  const edit = state.edit;
  const trial = periodTrial();
  return '<div class="slip"><h3>Change the month</h3>' +
    '<p class="note"><b>The month keeps its shape.</b> Dated rules — leave, days ' +
    "asked off, duties already set — move with it, so each one still falls on the " +
    "same day of the roster. The demand follows the new calendar, so weekends stay " +
    "the quieter days. Nothing is kept unless the engine accepts the whole month.</p>" +
    (edit.error ? '<p class="warn">' + esc(edit.error) + "</p>" : "") +
    fieldRow("First day", true, '<input type="date" aria-label="First day" ' +
      'data-set="edit" data-name="start" value="' + esc(edit.start) + '">') +
    fieldRow("Days in the month", true,
      numberField("Days in the month", "edit", "days", edit.days, "1", 1)) +
    (trial ? ledger(periodWords(trial))
      : '<p class="warn">Give a real first day and a length between 1 and 62 ' +
        "days.</p>") +
    '<div class="doing">' +
    press("Apply the month", "save-period", false, state.busy || !trial) +
    press("Cancel", "cancel-edit", true, state.busy) + "</div></div>";
}

function periodPanel() {
  const inst = state.instance;
  if (!inst) return nothingYet(
    "Nothing is on the desk yet. The sample month is a real 31-day university " +
    "roster — 44 staff, three shifts a day, 33 rules — and every other step " +
    "reads from whatever is loaded here.", OPEN_IT, "sample");
  const span = inst.horizon;
  const weekend = (span.weekend_days || []).map(day => DAYS[day]).join(", ");
  const shut = span.holidays || [];
  const open = state.edit && state.edit.kind === "period";
  return ledger([
    ["Instance", inst.name],
    ["First day", longDate(span.start)],
    ["Last day", longDate(addDays(span.start, span.num_days - 1))],
    ["Days", span.num_days],
    ["Weekend", weekend || "none"],
    ["Holidays", shut.length ? shut.map(longDate).join("; ") : "none"]
  ]) + (open ? periodSlip() : '<div class="doing">' +
    press("Change the month", "edit-period", false, state.busy || !state.schema) +
    press("Reload the sample month", "sample", true, state.busy) + "</div>") +
    (state.schema ? "" : '<p class="warn">The rule catalogue could not be read ' +
      "from the engine, so a dated rule could not be moved safely and the month " +
      "cannot be changed until the engine answers again.</p>");
}

function scopeRules(inst, id) {
  return inst.rules.filter(rule => {
    const scope = rule.scope || {};
    return scope.kind === "employees" && (scope.ids || []).indexOf(id) >= 0;
  });
}

function withoutPerson(inst, id) {
  const rules = [], lost = [], trimmed = [];
  inst.rules.forEach(rule => {
    const scope = rule.scope || {};
    if (scope.kind !== "employees" || (scope.ids || []).indexOf(id) < 0) {
      rules.push(rule);
      return;
    }
    const left = scope.ids.filter(one => one !== id);
    if (!left.length) { lost.push(rule); return; }
    trimmed.push(rule.id);
    rules.push(Object.assign({}, rule, { scope: { kind: "employees", ids: left } }));
  });
  return { employees: inst.employees.filter(one => one.id !== id),
           rules: rules, lost: lost, trimmed: trimmed };
}

function renameInRules(inst, from, to) {
  return inst.rules.map(rule => {
    const scope = rule.scope || {};
    if (scope.kind !== "employees" || (scope.ids || []).indexOf(from) < 0) return rule;
    return Object.assign({}, rule, { scope: { kind: "employees",
      ids: scope.ids.map(one => one === from ? to : one) } });
  });
}

function nextStaffId(inst) {
  const seen = {};
  let stem = "E", width = 2, most = 0;
  inst.employees.forEach(person => {
    seen[person.id] = true;
    const parts = /^(\D*)(\d+)$/.exec(person.id);
    if (!parts) return;
    stem = parts[1];
    width = Math.max(width, parts[2].length);
    most = Math.max(most, parseInt(parts[2], 10));
  });
  let next = most + 1;
  while (seen[stem + String(next).padStart(width, "0")]) next += 1;
  return stem + String(next).padStart(width, "0");
}

function usualContract(inst) {
  const count = {};
  inst.employees.forEach(person => {
    if (person.contract) count[person.contract] = (count[person.contract] || 0) + 1;
  });
  return Object.keys(count).sort((a, b) => count[b] - count[a])[0] || "permanent";
}

function personEdit(person) {
  const inst = state.instance;
  return { kind: "person",
           was: person ? person.id : "",
           id: person ? person.id : nextStaffId(inst),
           name: person ? person.name || "" : "",
           roles: person ? person.roles.slice() : [],
           contract: person ? person.contract || "" : usualContract(inst),
           error: "" };
}

function personSlip() {
  const edit = state.edit;
  const inst = state.instance;
  const tied = edit.was ? scopeRules(inst, edit.was) : [];
  const renaming = Boolean(edit.was) && edit.id !== edit.was;
  return '<div class="slip"><h3>' +
    (edit.was ? "Edit " + esc(edit.was) : "Add someone to the roll") + "</h3>" +
    '<p class="note"><b>A staff number is how every rule names a person.</b> ' +
    "Change it and the rules that name them are rewritten to match, so nothing is " +
    "left pointing at somebody who is no longer on the roll. The roles decide which " +
    "duties this person can be given, and the contract is what a rule scoped to a " +
    "kind of employment will look for.</p>" +
    (edit.error ? '<p class="warn">' + esc(edit.error) + "</p>" : "") +
    fieldRow("Staff number", true,
      textField("Staff number", "edit", edit.id, nextStaffId(inst), "id")) +
    fieldRow("Name", false,
      textField("Name", "edit", edit.name, "as it should read on the roster", "name")) +
    fieldRow("Roles held", true, picksOf("Roles held", "roles", edit.roles,
      inst.roles.map(role => [role.id, role.id, false, role.name]), "hold")) +
    fieldRow("Contract", false, listField("Contract", "edit", "contract",
      edit.contract, contracts(inst), "permanent")) +
    (renaming && tied.length ? '<p class="note">' + tied.length + " rule" +
      (tied.length === 1 ? " names " : "s name ") + esc(edit.was) +
      " and will be rewritten to " + esc(edit.id) + ": " +
      esc(tied.map(rule => rule.label).join("; ")) + "</p>" : "") +
    '<div class="doing">' +
    press(edit.was ? "Save" : "Add to the roll", "save-person", false, state.busy) +
    press("Cancel", "cancel-edit", true, state.busy) + "</div></div>";
}

function personRow(person) {
  const open = Boolean(state.edit) && state.edit.kind === "person" &&
               state.edit.was === person.id;
  return '<li data-on="' + open + '"><p><span class="chip">' + esc(person.id) +
    "</span></p><p>" + esc(person.name || person.id) + '<span class="says">' +
    esc((person.roles.join(", ") || "no role") +
        (person.contract ? " · " + person.contract : "")) + "</span></p>" +
    '<p class="doing">' + press("Edit", "edit-person", true, state.busy, person.id) +
    press("Remove", "drop-person", true, state.busy, person.id) + "</p></li>";
}

function staffPanel() {
  const inst = state.instance;
  if (!inst) return nothingYet("The staff list arrives with the month.",
                               OPEN_IT, "sample");
  const qualified = {};
  inst.roles.forEach(role => { qualified[role.id] = 0; });
  inst.employees.forEach(person => person.roles.forEach(role => {
    qualified[role] = (qualified[role] || 0) + 1;
  }));
  const doubling = inst.employees.filter(person => person.roles.length > 1).length;
  const open = state.edit && state.edit.kind === "person";
  const find = state.staffFind.trim().toLowerCase();
  const shown = !find ? inst.employees : inst.employees.filter(person =>
    (person.id + " " + (person.name || "")).toLowerCase().indexOf(find) >= 0);
  return tally([["on the roll", inst.employees.length],
                ["roles", inst.roles.length],
                ["hold more than one role", doubling]]) +
    ledger(inst.roles.map(role =>
      [role.id, role.name + " — " + qualified[role.id] + " qualified"])) +
    (open ? personSlip() : '<div class="doing">' +
      press("Add someone", "add-person", false, state.busy) +
      (state.gone ? press("Put " + state.gone.person.id + " back", "unremove",
                          true, state.busy) : "") + "</div>") +
    '<div class="sift"><label for="onroll">Find</label>' +
    '<input id="onroll" type="search" data-set="staff-find" autocomplete="off" ' +
    'value="' + esc(state.staffFind) + '" placeholder="staff number or name">' +
    '<span class="count">' + (find ? shown.length + " of " +
      inst.employees.length + " on the roll" : inst.employees.length +
      " on the roll") + "</span></div>" +
    (shown.length ? '<ul class="entries">' + shown.map(personRow).join("") + "</ul>"
      : '<p class="none">Nobody on the roll answers to that.</p>');
}

function shiftEdit(shift) {
  return { kind: "shift", id: shift.id, name: shift.name || "",
           start: clock(shift.start_min),
           hours: String(shift.duration_min / 60),
           night: Boolean(shift.counts_as_night), error: "" };
}

function shiftTrial() {
  const edit = state.edit;
  const from = parseClock(edit.start);
  const span = Math.round((parseFloat(edit.hours) || 0) * 60);
  if (from === null || span < 15 || span > 1440) return null;
  return { start_min: from, duration_min: span };
}

function shiftSlip() {
  const edit = state.edit;
  const trial = shiftTrial();
  return '<div class="slip"><h3>Edit the ' + esc(edit.id) + " shift</h3>" +
    '<p class="note"><b>The letter stays as it is.</b> Every line of demand and ' +
    "every rule that names a shift is keyed to it, so renaming it would leave them " +
    "pointing at nothing. The clock time, the length and whether it counts as a " +
    "night are yours — and the night flag is what the night rules and the rest gaps " +
    "are read against, not the hour on the clock.</p>" +
    (edit.error ? '<p class="warn">' + esc(edit.error) + "</p>" : "") +
    fieldRow("Name", false,
      textField("Name", "edit", edit.name, edit.id, "name")) +
    fieldRow("Starts at", true, '<input type="time" aria-label="Starts at" ' +
      'data-set="edit" data-name="start" value="' + esc(edit.start) + '">') +
    fieldRow("Hours long", true,
      numberField("Hours long", "edit", "hours", edit.hours, "0.25", 0.25)) +
    fieldRow("Counts as a night", false,
      yesNo("Counts as a night", "night", edit.night, "edit-flag")) +
    ledger([["Would run", trial
      ? clock(trial.start_min) + " to " + clock(trial.start_min + trial.duration_min) +
        (trial.start_min + trial.duration_min >= 1440 ? " the next day" : "") +
        " · " + hours(trial.duration_min)
      : "not a real time yet"],
      ["Counts as", edit.night ? "a night shift" : "a day shift"]]) +
    (trial ? "" : '<p class="warn">Give a clock time and a length between a ' +
      "quarter of an hour and 24 hours.</p>") +
    '<div class="doing">' +
    press("Save the shift", "save-shift", false, state.busy || !trial) +
    press("Cancel", "cancel-edit", true, state.busy) + "</div></div>";
}

function shiftRow(shift, needed) {
  const open = Boolean(state.edit) && state.edit.kind === "shift" &&
               state.edit.id === shift.id;
  return '<li data-on="' + open + '"><p><span class="chip' +
    (shift.counts_as_night ? " night" : "") + '">' + esc(shift.id) +
    "</span></p><p>" + esc(shift.name || shift.id) + '<span class="says">' +
    esc(clock(shift.start_min) + "–" + clock(shift.start_min + shift.duration_min) +
        " · " + hours(shift.duration_min) +
        (shift.counts_as_night ? " · counts as a night" : "") + " · " +
        (needed[shift.id] || 0) + " needed this month") + "</span></p>" +
    '<p class="doing">' + press("Edit", "edit-shift", true, state.busy, shift.id) +
    "</p></li>";
}

const MARKS = { unavailable: "away", day_off_request: "asked off",
                shift_off_request: "asked off", shift_request: "asked for",
                fixed_assignment: "set duty" };

function ruleReaches(rule, person) {
  const scope = rule.scope || {};
  if (!scope.kind || scope.kind === "all") return true;
  if (scope.kind === "employees") return (scope.ids || []).indexOf(person.id) >= 0;
  if (scope.kind === "roles") {
    return (scope.ids || []).some(role => person.roles.indexOf(role) >= 0);
  }
  if (scope.kind === "contracts") return (scope.ids || []).indexOf(person.contract) >= 0;
  return false;
}

function marksFor(inst, person) {
  const marks = {};
  inst.rules.forEach(rule => {
    if (!MARKS[rule.type] || !ruleReaches(rule, person)) return;
    const dated = datedParams(rule.type).filter(param =>
      !blank((rule.params || {})[param.name]));
    dated.forEach(param => {
      const value = rule.params[param.name];
      (param.kind === "day" ? [value] : value).forEach(iso => {
        (marks[iso] || (marks[iso] = [])).push({
          word: MARKS[rule.type], label: rule.label,
          hard: rule.severity === "hard" });
      });
    });
  });
  return marks;
}

function dutiesFor(id) {
  const out = state.solved;
  if (!out) return null;
  const row = out.roster.rows.filter(one => one.employee === id)[0];
  if (!row) return {};
  const byDate = {};
  row.days.forEach((cell, index) => {
    if (cell) byDate[out.roster.dates[index]] = cell;
  });
  return byDate;
}

function monthWeeks(span) {
  const weeks = [];
  let week = [];
  for (let pad = 0; pad < weekdayOf(span.start); pad += 1) week.push(null);
  for (let day = 0; day < span.num_days; day += 1) {
    week.push(day);
    if (week.length === 7) { weeks.push(week); week = []; }
  }
  if (week.length) {
    while (week.length < 7) week.push(null);
    weeks.push(week);
  }
  return weeks;
}

function shiftsBy(inst) {
  const byId = {};
  inst.shifts.forEach(shift => { byId[shift.id] = shift; });
  return byId;
}

function monthCell(index, look) {
  if (index === null) return '<td class="pad"></td>';
  const iso = addDays(look.span.start, index);
  const cell = look.duties ? look.duties[iso] : null;
  const noted = look.marks[iso] || [];
  const shift = cell ? (look.shifts[cell.shift] || {}) : null;
  const said = [longDate(iso)];
  if (cell) said.push((shift.name || cell.shift) + " " + clock(shift.start_min) +
    "–" + clock(shift.start_min + shift.duration_min) + " as " + cell.role);
  noted.forEach(one => said.push(one.word + " — " + one.label));
  if (!cell && !noted.length) said.push(look.duties ? "no duty" : "nothing fixed yet");
  return '<td class="' + (look.resting(iso) ? "rest" : "") + (cell ? " on" : "") +
    (shift && shift.counts_as_night ? " night" : "") +
    (noted.length ? " noted" : "") + '" title="' + esc(said.join(" · ")) + '">' +
    "<i>" + isoDate(iso).getDate() + "</i>" +
    (cell ? "<b>" + esc(cell.shift) + "</b><span>" +
      esc(clock(shift.start_min) + "–" + clock(shift.start_min + shift.duration_min)) +
      "</span><span>" + esc(cell.role) + "</span>" : "") +
    noted.map(one => '<span class="mark' + (one.hard ? " firm" : "") + '">' +
      esc(one.word) + "</span>").join("") + "</td>";
}

function personMonth(inst) {
  const person = inst.employees.filter(one => one.id === state.pick)[0];
  if (!person) return "";
  const look = { span: inst.horizon, duties: dutiesFor(person.id),
                 marks: marksFor(inst, person), shifts: shiftsBy(inst),
                 resting: restDays(inst) };
  const weekend = inst.horizon.weekend_days || [];
  const load = state.solved
    ? (state.solved.workload.filter(one => one.employee === person.id)[0] || null)
    : null;
  return '<div class="slip who"><h4>' + esc(person.id) + " · " +
    esc(person.name || person.id) + "</h4>" +
    '<p class="note">Holds <b>' + esc(person.roles.join(", ") || "no role") +
    "</b>" + (person.contract ? " · " + esc(person.contract) : "") + " · " +
    esc(longDate(inst.horizon.start)) + " to " +
    esc(longDate(addDays(inst.horizon.start, inst.horizon.num_days - 1))) + "</p>" +
    (load ? tally([["duties", num(load.duties || 0)],
                   ["hours", num(load.hours || 0)],
                   ["nights", num(load.nights || 0)],
                   ["weekends worked", num(load.weekends || 0)],
                   ["longest run", num(load.longest_run || 0) + " days"]]) : "") +
    (look.duties ? "" : '<p class="key">No roster has been generated for this ' +
      "month yet, so the calendar shows only what the rules already fix — leave, " +
      "days asked off, duties already set. Generate on step 6 and the duties " +
      "appear here.</p>") +
    '<div class="cal"><table><thead><tr>' + DAYS.map((day, index) =>
      '<th scope="col"' + (weekend.indexOf(index) >= 0 ? ' class="rest"' : "") +
      ">" + day.slice(0, 3) + "</th>").join("") + "</tr></thead><tbody>" +
    monthWeeks(inst.horizon).map(week => "<tr>" + week.map(index =>
      monthCell(index, look)).join("") + "</tr>").join("") +
    "</tbody></table></div>" +
    '<p class="key">Days outside the month are hatched. Rest days are tinted, ' +
    "nights are violet, and anything the rules already say about a day is printed " +
    "on it in red.</p>" +
    '<div class="doing">' + press("Close", "pick", true, state.busy, person.id) +
    "</div></div>";
}

function personFinder(inst) {
  const find = state.pickFind.trim().toLowerCase();
  const hits = !find ? [] : inst.employees.filter(person =>
    (person.id + " " + (person.name || "")).toLowerCase().indexOf(find) >= 0);
  const most = hits.slice(0, 20);
  return '<h3 class="minor">One person\'s month</h3>' +
    '<div class="sift"><label for="look">Find</label>' +
    '<input id="look" type="search" data-set="pick-find" autocomplete="off" ' +
    'value="' + esc(state.pickFind) + '" placeholder="staff number or name">' +
    (find ? '<span class="count">' + hits.length + " match" +
      (hits.length === 1 ? "" : "es") + "</span>" : "") + "</div>" +
    (find && !hits.length ? '<p class="none">Nobody on the roll answers to that.</p>'
      : "") +
    (most.length ? '<div class="hits">' + most.map(person =>
      '<button class="quiet' + (state.pick === person.id ? " on" : "") + '" ' +
      'type="button" data-do="pick" data-id="' + esc(person.id) + '" ' +
      'aria-pressed="' + (state.pick === person.id) + '">' +
      esc(person.id + " · " + (person.name || person.id)) + "</button>").join("") +
      (hits.length > most.length ? '<span class="count">and ' +
        (hits.length - most.length) + " more — narrow the search</span>" : "") +
      "</div>" : "") +
    (state.pick ? personMonth(inst) : '<p class="key">Look somebody up by name or ' +
      "by staff number to see their whole month at once — every duty they hold, " +
      "once a roster has been generated, and before that whatever the rules " +
      "already fix about their days.</p>");
}

function shiftsPanel() {
  const inst = state.instance;
  if (!inst) return nothingYet("The shifts and the demand arrive with the month.",
                               OPEN_IT, "sample");
  const needed = {};
  let total = 0;
  inst.demand.forEach(line => {
    needed[line.shift] = (needed[line.shift] || 0) + line.required;
    total += line.required;
  });
  const open = state.edit && state.edit.kind === "shift";
  return tally([["shifts a day", inst.shifts.length],
                ["person-shifts to fill", total],
                ["demand lines", inst.demand.length]]) +
    (open ? shiftSlip() : "") +
    '<ul class="entries">' +
    inst.shifts.map(shift => shiftRow(shift, needed)).join("") + "</ul>" +
    personFinder(inst);
}

function restDays(inst) {
  const weekly = new Set(inst.horizon.weekend_days || []);
  const shut = new Set(inst.horizon.holidays || []);
  return iso => weekly.has((isoDate(iso).getDay() + 6) % 7) || shut.has(iso);
}

function budget() {
  return '<div class="dial"><label for="budget">Time to spend searching</label>' +
    '<select id="budget" data-set="seconds">' +
    [15, 30, 60, 120].map(count => '<option value="' + count + '"' +
      (count === state.seconds ? " selected" : "") + ">" + count +
      " seconds</option>").join("") + "</select>" +
    "<span>longer is better; 30 seconds is enough for a month this size</span></div>";
}

function rosterRows(out) {
  const view = state.view;
  const find = view.find.trim().toLowerCase();
  const load = {};
  out.workload.forEach(person => { load[person.employee] = person; });
  const hurt = out.violations_by_employee || {};
  return out.roster.rows.filter(row => {
    const stats = load[row.employee] || {};
    if (view.role && (stats.roles || []).indexOf(view.role) < 0) return false;
    if (view.only && !(hurt[row.employee] || []).length) return false;
    if (!find) return true;
    return (row.employee + " " + (stats.name || "")).toLowerCase().indexOf(find) >= 0;
  });
}

function litDuties(out) {
  const mark = { rows: {}, cells: {}, days: {}, month: false, seen: 0, people: 0 };
  if (!state.lit) return mark;
  (out.score.violations || []).forEach(one => {
    if (one.rule_id !== state.lit) return;
    mark.seen += 1;
    const days = one.days || [];
    if (one.employee && days.length) {
      const held = mark.cells[one.employee] || (mark.cells[one.employee] = {});
      days.forEach(day => { held[day] = true; });
    } else if (one.employee) mark.rows[one.employee] = true;
    else if (days.length) days.forEach(day => { mark.days[day] = true; });
    else mark.month = true;
  });
  mark.people = Object.keys(mark.cells).length + Object.keys(mark.rows).length;
  return mark;
}

function grid(out) {
  const inst = state.instance;
  const resting = restDays(inst);
  const shifts = {};
  inst.shifts.forEach(shift => { shifts[shift.id] = shift; });
  const load = {};
  out.workload.forEach(person => { load[person.employee] = person; });
  const dates = out.roster.dates;
  const lit = litDuties(out);
  const onDuty = dates.map(() => 0);
  out.roster.rows.forEach(row => row.days.forEach((cell, index) => {
    if (cell) onDuty[index] += 1;
  }));

  const heads = dates.map((iso, index) => {
    const off = resting(iso);
    const when = isoDate(iso);
    return '<th scope="col" class="day' + (off ? " rest" : "") + '" data-day="' +
      index + '" data-lit="' + (lit.days[index] === true) + '" title="' +
      esc(longDate(iso)) + (off ? " · rest day" : "") + '"><i>' +
      DAYS[(when.getDay() + 6) % 7].slice(0, 2) + "</i>" + when.getDate() + "</th>";
  });

  const shown = rosterRows(out);
  const rows = shown.map(row => {
    const stats = load[row.employee] || {};
    const held = lit.cells[row.employee] || {};
    const all = lit.rows[row.employee] === true;
    const cells = row.days.map((cell, index) => {
      const iso = dates[index];
      const mark = ["day"];
      if (resting(iso)) mark.push("rest");
      if (!cell) mark.push("off");
      else if ((shifts[cell.shift] || {}).counts_as_night) mark.push("night");
      if (held[index] || (all && cell)) mark.push("lit");
      const said = esc(row.employee + " " + (stats.name || "") + " · " + (cell
        ? (shifts[cell.shift] || {}).name + " · " + cell.role
        : "off duty") + " · " + longDate(iso));
      return '<td class="' + mark.join(" ") + '" data-day="' + index +
        '" data-say="' + said + '" title="' + said + '">' +
        (cell ? esc(cell.shift) : "·") + "</td>";
    }).join("");
    const worked = num(stats.duties || 0) + " duties · " + num(stats.hours || 0) +
      " hours · " + num(stats.nights || 0) + " nights · " +
      num(stats.weekends || 0) + " weekends worked";
    const open = state.who === row.employee;
    return '<tr><th scope="row" data-on="' + open + '" data-lit="' +
      (all || Object.keys(held).length > 0) + '"><button type="button" class="name"' +
      ' data-do="who" data-id="' + esc(row.employee) + '" aria-expanded="' + open +
      '" data-say="' + esc(row.employee + " " + (stats.name || "") + " · " + worked) +
      '"><i>' + esc(row.employee) + "</i>" + esc(stats.name || "") +
      "</button></th>" + cells +
      ['<td class="sum">' + num(stats.duties || 0) + "</td>",
       '<td class="sum">' + num(stats.hours || 0) + "</td>",
       '<td class="sum">' + num(stats.nights || 0) + "</td>",
       '<td class="sum">' + num(stats.weekends || 0) + "</td>"].join("") + "</tr>";
  }).join("");

  if (!shown.length) {
    return '<p class="none">No one on the sheet answers to that. ' +
      "Clear the search to see the month again.</p>";
  }
  const feet = onDuty.map((count, index) =>
    '<td class="day' + (resting(dates[index]) ? " rest" : "") + '" data-day="' +
    index + '" data-lit="' + (lit.days[index] === true) + '">' + count +
    "</td>").join("");
  return '<div class="roll"><table><thead><tr>' +
    '<th scope="col">' + esc(inst.name) + "</th>" + heads.join("") +
    '<th scope="col" class="sum">d</th><th scope="col" class="sum">h</th>' +
    '<th scope="col" class="sum">n</th><th scope="col" class="sum">w</th>' +
    "</tr></thead><tbody>" + rows + "</tbody><tfoot><tr>" +
    '<th scope="row">on duty</th>' + feet +
    '<td class="sum" colspan="4">' + onDuty.reduce((a, b) => a + b, 0) +
    "</td></tr></tfoot></table></div>" +
    '<p class="key">M morning · E evening · <span class="night">N night</span> · ' +
    "· off duty · shaded columns are weekends and holidays · " +
    "d duties, h hours, n nights, w weekends worked · " +
    "the head count under each day is for the whole month, not the filtered sheet · " +
    "point at a duty to read it in the margin, or open a name for that person's " +
    "month</p>";
}
const FAMILIES = [
  ["Cover the posts", ["coverage", "headcount_per_shift", "fixed_assignment"]],
  ["Hours and rest", ["hours_per_window", "total_hours_range", "min_rest_hours",
                      "max_working_days_per_window", "min_days_off_per_window"]],
  ["Runs of work and rest", ["max_consecutive_working_days",
                             "min_consecutive_working_days",
                             "min_consecutive_days_off", "max_consecutive_days_off"]],
  ["Nights and shift patterns", ["max_night_shifts", "max_consecutive_same_shift",
                                 "forbidden_shift_sequence", "shift_type_count_range"]],
  ["Weekends", ["max_weekends_worked", "complete_weekends"]],
  ["Fair shares", ["balance_workload", "total_shifts_range"]],
  ["What people ask for", ["day_off_request", "shift_off_request", "shift_request",
                           "shift_preference", "unavailable"]]
];

function typeCard(type) {
  const kinds = (state.schema && state.schema.rule_types) || [];
  return kinds.filter(card => card.type === type)[0] || null;
}

function families() {
  const kinds = (state.schema && state.schema.rule_types) || [];
  const left = {};
  kinds.forEach(card => { left[card.type] = card; });
  const out = [];
  FAMILIES.forEach(family => {
    const held = family[1].filter(type => left[type]).map(type => {
      const card = left[type];
      delete left[type];
      return card;
    });
    if (held.length) out.push([family[0], held]);
  });
  const rest = Object.keys(left).map(type => left[type]);
  if (rest.length) out.push(["Other rules", rest]);
  return out;
}

function dates(inst) {
  const all = [];
  for (let day = 0; day < inst.horizon.num_days; day += 1) {
    all.push(addDays(inst.horizon.start, day));
  }
  return all;
}

function contracts(inst) {
  const seen = {};
  inst.employees.forEach(person => {
    if (person.contract) seen[person.contract] = true;
  });
  return Object.keys(seen).sort();
}

function scopeWords(scope) {
  if (!scope || scope.kind === "all" || !scope.ids || !scope.ids.length) {
    return "everyone";
  }
  const ids = scope.ids.join(", ");
  if (scope.kind === "employees") return ids;
  if (scope.kind === "roles") return "anyone holding " + ids;
  return ids + " staff";
}

function shortDate(iso) {
  const day = isoDate(iso);
  return day.getDate() + " " + MONTHS[day.getMonth()].slice(0, 3);
}

function dayRuns(list) {
  const runs = [];
  list.slice().sort().forEach(iso => {
    const last = runs[runs.length - 1];
    if (last && addDays(last[1], 1) === iso) last[1] = iso;
    else runs.push([iso, iso]);
  });
  return runs.map(run => run[0] === run[1] ? shortDate(run[0])
                  : shortDate(run[0]) + " to " + shortDate(run[1])).join(", ");
}

function blank(value) {
  if (Array.isArray(value)) return !value.length;
  return value === "" || value === null || value === undefined;
}

function shiftName(id) {
  const inst = state.instance;
  const found = inst ? inst.shifts.filter(shift => shift.id === id) : [];
  return found.length ? (found[0].name || found[0].id) : id;
}

function valueWords(kind, value) {
  if (kind === "days") return dayRuns(value);
  if (kind === "day") return shortDate(value);
  if (kind === "shifts") return value.map(shiftName).join(" then ");
  if (kind === "shift") return shiftName(value);
  if (kind === "bool") return value ? "yes" : "no";
  return String(value);
}

function paramWords(rule) {
  const card = typeCard(rule.type);
  const params = rule.params || {};
  const said = card
    ? card.params.filter(param => !blank(params[param.name])).map(param =>
        param.label.replace(/ *\(.*\)$/, "") + " " +
        valueWords(param.kind, params[param.name]))
    : Object.keys(params).map(name => name + " " + params[name]);
  return said.join(" · ");
}

function fieldRow(label, required, control) {
  return '<div class="field"><span>' + esc(label) +
    (required ? "<i> required</i>" : "") + "</span>" + control + "</div>";
}

function selectOf(label, set, name, chosen, options, empty) {
  const head = empty === undefined ? ""
    : '<option value=""' + (blank(chosen) ? " selected" : "") + ">" +
      esc(empty) + "</option>";
  return '<select aria-label="' + esc(label) + '" data-set="' + set + '"' +
    (name ? ' data-name="' + esc(name) + '"' : "") + ">" + head +
    options.map(option => '<option value="' + esc(option[0]) + '"' +
      (String(option[0]) === String(chosen) ? " selected" : "") + ">" +
      esc(option[1]) + "</option>").join("") + "</select>";
}

function numberField(label, set, name, value, step, least) {
  return '<input type="number" aria-label="' + esc(label) + '" data-set="' + set +
    '"' + (name ? ' data-name="' + esc(name) + '"' : "") +
    ' step="' + step + '"' + (least === undefined ? "" : ' min="' + least + '"') +
    ' value="' + esc(blank(value) ? "" : value) + '">';
}

function picksOf(label, name, chosen, options, set) {
  const on = {};
  (chosen || []).forEach(value => { on[value] = true; });
  return '<div class="picks" role="group" aria-label="' + esc(label) + '">' +
    options.map(option => '<label class="pick' + (on[option[0]] ? " on" : "") +
      (option[2] ? " rest" : "") + '"><input type="checkbox" data-set="' +
      (set || "pick") + '" data-name="' + esc(name) + '" value="' +
      esc(option[0]) + '"' +
      (on[option[0]] ? " checked" : "") + ">" + esc(option[1]) +
      (option[3] ? "<i>" + esc(option[3]) + "</i>" : "") + "</label>").join("") +
    "</div>";
}

function yesNo(label, name, value, set) {
  return '<div class="picks" role="group" aria-label="' + esc(label) +
    '"><label class="pick' + (value ? " on" : "") +
    '"><input type="checkbox" data-set="' + (set || "flag") + '" data-name="' +
    esc(name) + '" aria-label="' + esc(label) + '"' + (value ? " checked" : "") +
    ">" + (value ? "yes" : "no") + "</label></div>";
}

function dayPicks(inst) {
  const isRest = restDays(inst);
  return dates(inst).map(iso => [iso, String(isoDate(iso).getDate()), isRest(iso),
                                 DAYS[(isoDate(iso).getDay() + 6) % 7].slice(0, 1)]);
}

function shiftPicks(inst) {
  return inst.shifts.map(shift => [shift.id, shift.id, false, shift.name || ""]);
}

function textField(label, set, value, hint, name) {
  return '<input type="text" aria-label="' + esc(label) + '" data-set="' + set +
    '"' + (name ? ' data-name="' + esc(name) + '"' : "") +
    ' value="' + esc(value || "") + '" placeholder="' + esc(hint || "") + '">';
}

function listField(label, set, name, value, options, hint) {
  const list = "list-" + name;
  return '<input type="text" aria-label="' + esc(label) + '" data-set="' + set +
    '" data-name="' + esc(name) + '" list="' + list + '" value="' +
    esc(value || "") + '" placeholder="' + esc(hint || "") + '">' +
    '<datalist id="' + list + '">' + options.map(one =>
      '<option value="' + esc(one) + '"></option>').join("") + "</datalist>";
}

function multiOf(label, options, chosen) {
  const on = {};
  (chosen || []).forEach(value => { on[value] = true; });
  return '<select multiple aria-label="' + esc(label) + '" data-set="scope-ids">' +
    options.map(option => '<option value="' + esc(option[0]) + '"' +
      (on[option[0]] ? " selected" : "") + ">" + esc(option[1]) +
      "</option>").join("") + "</select>";
}

function paramField(param) {
  const inst = state.instance;
  const value = state.draft.params[param.name];
  const label = param.label;
  const spare = param.required ? undefined : "any";
  let control;
  if (param.kind === "bool") {
    control = yesNo(label, param.name, value, "flag");
  } else if (param.kind === "choice") {
    control = selectOf(label, "param", param.name, value,
                       param.options.map(option => [option, option]), spare);
  } else if (param.kind === "shift") {
    control = selectOf(label, "param", param.name, value,
      inst.shifts.map(shift => [shift.id, shift.id + " · " + (shift.name || shift.id)]),
      spare);
  } else if (param.kind === "role") {
    control = selectOf(label, "param", param.name, value,
      inst.roles.map(role => [role.id, role.id + " · " + (role.name || role.id)]),
      spare);
  } else if (param.kind === "day") {
    control = selectOf(label, "param", param.name, value,
      dates(inst).map(iso => [iso, longDate(iso)]), spare);
  } else if (param.kind === "days") {
    control = picksOf(label, param.name, value, dayPicks(inst));
  } else if (param.kind === "shifts") {
    control = picksOf(label, param.name, value, shiftPicks(inst));
  } else {
    control = numberField(label, "param", param.name, value,
                          param.kind === "float" ? "0.5" : "1", param.minimum);
  }
  return fieldRow(label, param.required, control);
}

const SCOPES = [["all", "everyone"], ["employees", "named people"],
                ["roles", "everyone holding a role"],
                ["contracts", "a kind of contract"]];

function scopeChoices(inst, kind) {
  if (kind === "employees") {
    return inst.employees.map(person =>
      [person.id, person.id + " · " + (person.name || person.id)]);
  }
  if (kind === "roles") {
    return inst.roles.map(role => [role.id, role.id + " · " + (role.name || role.id)]);
  }
  if (kind === "contracts") return contracts(inst).map(name => [name, name]);
  return [];
}

function catalogue(chosen) {
  return '<select aria-label="Kind of rule" data-set="type">' +
    families().map(family => '<optgroup label="' + esc(family[0]) + '">' +
      family[1].map(card => '<option value="' + esc(card.type) + '"' +
        (card.type === chosen ? " selected" : "") + ">" + esc(card.label) +
        "</option>").join("") + "</optgroup>").join("") + "</select>";
}

function slip() {
  const draft = state.draft;
  const inst = state.instance;
  const card = typeCard(draft.type);
  const ids = scopeChoices(inst, draft.scope.kind);
  return '<div class="slip"><h3>' +
    (draft.editing ? "Edit this rule" : "Add a rule") + "</h3>" +
    (card ? '<p class="note"><b>' + esc(card.help) + "</b> " +
            esc(card.example) + "</p>" : "") +
    (draft.error ? '<p class="warn">' + esc(draft.error) + "</p>" : "") +
    fieldRow("Kind of rule", true, catalogue(draft.type)) +
    (card ? card.params.map(paramField).join("") : "") +
    fieldRow("Applies to", true,
             selectOf("Applies to", "scope-kind", "", draft.scope.kind, SCOPES)) +
    (ids.length ? fieldRow("Which of them", true,
                           multiOf("Which of them", ids, draft.scope.ids)) : "") +
    fieldRow("Severity", true, selectOf("Severity", "severity", "", draft.severity,
      [["hard", "hard · must hold"], ["soft", "soft · a preference"]])) +
    (draft.severity === "soft"
      ? fieldRow("Weight against other soft rules", false,
                 numberField("Weight", "weight", "", draft.weight, "0.5", 0)) : "") +
    fieldRow("How it should read in the report", false,
             textField("How it should read in the report", "label", draft.label,
                       autoLabel(draft))) +
    '<div class="doing">' +
    press(draft.editing ? "Save the rule" : "Add the rule", "save-rule", false,
          state.busy) +
    press("Cancel", "cancel-rule", true) + "</div></div>";
}

function autoLabel(draft) {
  const card = typeCard(draft.type);
  const head = card ? card.label : draft.type;
  const who = scopeWords(draft.scope);
  return who === "everyone" ? head : head + " — " + who;
}

function defaultFor(param) {
  if (param.kind === "days" || param.kind === "shifts") {
    return Array.isArray(param.default) ? param.default.slice() : [];
  }
  if (param.default === undefined || param.default === null) {
    return param.kind === "bool" ? false : "";
  }
  return param.default;
}

function blankDraft(type) {
  const card = typeCard(type);
  const params = {};
  (card ? card.params : []).forEach(param => {
    params[param.name] = defaultFor(param);
  });
  return { type: type, severity: card ? card.default_severity : "soft",
           weight: 3, label: "", scope: { kind: "all", ids: [] },
           params: params, editing: null, fromLine: null, error: "" };
}

function taken(extra) {
  const seen = {};
  state.instance.rules.forEach(rule => { seen[rule.id] = true; });
  (extra || []).forEach(rule => { seen[rule.id] = true; });
  return seen;
}

function freshId(type, seen) {
  const held = seen || taken();
  if (!held[type]) return type;
  let next = 2;
  while (held[type + "_" + next]) next += 1;
  return type + "_" + next;
}

function tidyParams(card, params) {
  const out = {};
  (card ? card.params : []).forEach(param => {
    const value = params[param.name];
    if (blank(value)) return;
    if (param.kind === "int") out[param.name] = parseInt(value, 10);
    else if (param.kind === "float") out[param.name] = parseFloat(value);
    else if (param.kind === "bool") out[param.name] = Boolean(value);
    else out[param.name] = Array.isArray(value) ? value.slice() : value;
  });
  return out;
}

function entries(rules) {
  if (!rules.length) {
    return '<p class="key">No rules at all — the engine would fill the grid and ' +
      "call anything legal.</p>";
  }
  return '<ul class="entries">' + rules.map(rule => {
    const editing = Boolean(state.draft) && state.draft.editing === rule.id;
    const words = paramWords(rule);
    return '<li data-on="' + editing + '"><p><span class="chip' +
      (rule.severity === "hard" ? " hard" : "") + '">' + esc(rule.severity) +
      "</span></p><p>" + esc(rule.label) + '<span class="says">' +
      esc(scopeWords(rule.scope)) + (words ? " · " + esc(words) : "") +
      (rule.severity === "soft" ? " · weight " + esc(rule.weight) : "") +
      " · " + esc(rule.id) + "</span></p><p class=\"doing\">" +
      press("Edit", "edit-rule", true, state.busy, rule.id) +
      press("Drop", "drop-rule", true, state.busy, rule.id) + "</p></li>";
  }).join("") + "</ul>";
}

const MEMO_HINT = "Nobody may work more than 6 days in a row.\n" +
  "Staff 07 is on leave from 15 to 19 September.\n" +
  "Every night shift needs at least two people on site.\n" +
  "LSG staff should not do more than 8 nights in the month.";

function certainty(value) {
  return Math.round((Number(value) || 0) * 100) + "% sure";
}

function drafted() {
  return state.read ? state.read.drafts.filter(one => one.rule) : [];
}

function proposalOn(line) {
  return (state.read ? state.read.drafts : []).filter(one => one.line === line)[0];
}

function nearest(types) {
  return types.map(type => {
    const card = typeCard(type);
    return card ? card.label : type;
  }).join(" · ");
}

function becomes(rule, confidence) {
  const card = typeCard(rule.type);
  const words = [scopeWords(rule.scope), paramWords(rule),
                 rule.severity === "hard" ? "must hold"
                                          : "a preference, weight " + num(rule.weight),
                 certainty(confidence)];
  return (card ? card.label : rule.type) + " · " +
    words.filter(word => word).join(" · ");
}

function proposal(draft) {
  const rule = draft.rule;
  const open = Boolean(state.draft) && state.draft.fromLine === draft.line;
  return '<li data-on="' + open + '"><p class="no">' + esc(draft.line) +
    '</p><p><span class="said">' + esc(draft.text) + "</span>" +
    (rule ? '<span class="became">' + esc(becomes(rule, draft.confidence)) +
            "</span>" : "") +
    (draft.problem ? '<span class="why">' + esc(draft.problem) + "</span>" : "") +
    (draft.assumptions || []).map(took =>
      '<span class="took">' + esc(took) + "</span>").join("") +
    (!rule && (draft.suggestions || []).length
      ? '<span class="became">nearest kinds — ' +
        esc(nearest(draft.suggestions)) + "</span>" : "") +
    '</p><p class="doing">' +
    (rule ? press("Accept", "take-draft", false, state.busy, String(draft.line)) : "") +
    press(rule ? "Edit first" : "Write it by hand", "open-draft", true,
          state.busy || !state.schema, String(draft.line)) +
    press("Discard", "skip-draft", true, state.busy, String(draft.line)) +
    "</p></li>";
}

function memoPanel() {
  const read = state.read;
  return '<div class="slip memo"><h3>Rules as the officials wrote them</h3>' +
    '<p class="note"><b>Paste the circular, one rule to a line.</b> Each line is ' +
    "read into a proposal you can accept, correct or discard. Nothing reaches the " +
    "register until you say so, and the wording is kept as the report's own." +
    "</p>" +
    (state.readError ? '<p class="warn">' + esc(state.readError) + "</p>" : "") +
    '<div class="field"><span>The wording<i> as written</i></span>' +
    '<textarea data-set="memo" rows="6" aria-label="The rules as the officials ' +
    'wrote them" placeholder="' + esc(MEMO_HINT) + '">' + esc(state.memoText) +
    "</textarea></div>" +
    '<div class="doing">' +
    press("Read these", "read-memo", false, state.busy) +
    (drafted().length > 1
      ? press("Accept all " + drafted().length, "take-all", true, state.busy) : "") +
    press("Close", "memo", true, state.busy) + "</div>" +
    (read ? tally([["statements read", read.counts.statements],
                   ["became proposals", read.counts.drafted],
                   ["could not be read", read.counts.unparsed]]) : "") +
    (read && !read.drafts.length
      ? '<p class="key">Every proposal has been dealt with.</p>' : "") +
    (read && read.drafts.length
      ? '<ul class="props">' + read.drafts.map(proposal).join("") + "</ul>" : "");
}

function rulesPanel() {
  const inst = state.instance;
  if (!inst) return nothingYet("The rules arrive with the month.", OPEN_IT, "sample");
  const hard = inst.rules.filter(rule => rule.severity === "hard");
  const kinds = {};
  inst.rules.forEach(rule => { kinds[rule.type] = true; });
  return tally([["hard rules", hard.length],
                ["soft rules", inst.rules.length - hard.length],
                ["kinds of rule in play", Object.keys(kinds).length],
                ["kinds the engine knows",
                 (state.schema && state.schema.rule_type_count) || "—"]]) +
    (state.schema ? "" : '<p class="warn">The rule catalogue could not be read ' +
      "from the engine, so nothing can be added until it answers again.</p>") +
    (state.draft ? slip() : '<div class="doing">' +
      press("Add a rule", "add-rule", false, state.busy || !state.schema) +
      press(state.memo ? "Close the memo" : "Paste rules as prose", "memo", true,
            state.busy) +
      (state.dropped
        ? press("Put back: " + state.dropped.label, "undrop", true, state.busy)
        : "") + "</div>") +
    (state.memo ? memoPanel() : "") +
    entries(inst.rules);
}

function checkPanel() {
  if (!state.instance) return nothingYet("There is no month to check yet.",
                                         OPEN_IT, "sample");
  const out = state.check;
  if (!out) return '<div class="empty"><p>The engine will weigh what every duty ' +
    "needs against the staff who are qualified and free, and name anything that " +
    "cannot work — before anyone waits on a search.</p>" +
    press("Check this month", "check") + "</div>";
  const summary = out.instance;
  const notes = out.problems.map(problem => ["cannot work", problem, "bad"])
    .concat(out.warnings.map(warning => ["worth knowing", warning]));
  return tally([[out.ok ? "the month is workable" : "the month cannot work",
                 out.ok ? "Yes" : "No"],
                ["person-shifts to fill", summary.demand_person_shifts],
                ["person-days available", summary.capacity_person_days],
                ["of capacity used", Math.round(summary.utilisation * 100) + "%"]]) +
    ledger(Object.keys(out.capacity_by_role).map(role => {
      const seat = out.capacity_by_role[role];
      return [role, seat.qualified_staff + " qualified · " +
                    seat.person_days_demanded + " of " +
                    seat.person_days_available + " person-days needed"];
    })) +
    (notes.length ? ledger(notes) : "") +
    press("Run the check again", "check", true);
}

function breaches(out) {
  const labels = {};
  state.instance.rules.forEach(rule => { labels[rule.id] = rule.label; });
  const groups = {};
  out.score.violations.forEach(breach => {
    const group = groups[breach.rule_id] || (groups[breach.rule_id] =
      { id: breach.rule_id, hard: breach.severity === "hard", seen: 0, cost: 0,
        says: [] });
    group.seen += 1;
    group.cost += breach.cost;
    if (group.says.length < 3) {
      group.says.push((breach.employee ? breach.employee + " — " : "") +
                      breach.message);
    }
  });
  const worst = Object.keys(groups).map(id => groups[id]).sort((one, two) =>
    (Number(two.hard) - Number(one.hard)) || (two.cost - one.cost));
  if (!worst.length) {
    return ledger([["every rule", "nothing given up — the whole rule set holds"]]);
  }
  return '<h3 class="minor">What the engine gave up · ' +
    "point at a rule to find it on the sheet</h3>" +
    '<ul class="breaks">' + worst.map(group => {
      const on = state.lit === group.id;
      const more = group.seen > group.says.length
        ? "; and " + (group.seen - group.says.length) + " more" : "";
      return '<li data-on="' + on + '"><button type="button" data-do="light"' +
        ' data-id="' + esc(group.id) + '" aria-pressed="' + on + '">' +
        '<span class="chip' + (group.hard ? " hard" : "") + '">' +
        (group.hard ? "hard" : "soft") + "</span><span>" +
        esc(labels[group.id] || group.id) +
        '<span class="says">' + esc(group.says.join("; ") + more) + "</span></span>" +
        '<span class="cost">' + group.seen +
        (group.seen === 1 ? " breach" : " breaches") + " · penalty " +
        num(group.cost) + "</span></button></li>";
    }).join("") + "</ul>";
}

function sift(out) {
  const view = state.view;
  const roles = {};
  out.workload.forEach(person =>
    (person.roles || []).forEach(role => { roles[role] = true; }));
  const shown = rosterRows(out).length;
  return '<div class="sift"><label for="find">Find</label>' +
    '<input id="find" type="search" data-set="find" autocomplete="off" value="' +
    esc(view.find) + '" placeholder="staff number or name">' +
    '<label for="holding">Holding</label>' +
    '<select id="holding" data-set="role"><option value="">any role</option>' +
    Object.keys(roles).sort().map(role => '<option value="' + esc(role) + '"' +
      (role === view.role ? " selected" : "") + ">" + esc(role) +
      "</option>").join("") + "</select>" +
    '<label><input class="box" type="checkbox" data-set="only"' +
    (view.only ? " checked" : "") + ">only staff a rule was broken for</label>" +
    '<span class="count">' + shown + " of " + out.roster.rows.length +
    " on the sheet</span></div>";
}

function personCard(out) {
  const id = state.who;
  const stats = out.workload.filter(one => one.employee === id)[0];
  const row = out.roster.rows.filter(one => one.employee === id)[0];
  if (!stats || !row) return "";
  const inst = state.instance;
  const who = inst.employees.filter(one => one.id === id)[0] || {};
  const resting = restDays(inst);
  const shifts = {};
  inst.shifts.forEach(shift => { shifts[shift.id] = shift; });
  const lit = litDuties(out);
  const held = lit.cells[id] || {};
  const all = lit.rows[id] === true;
  const strip = row.days.map((cell, index) => {
    const iso = out.roster.dates[index];
    const shift = cell ? (shifts[cell.shift] || {}) : null;
    return '<span data-shift="' + (shift && shift.counts_as_night ? "N" : "") +
      '" data-rest="' + resting(iso) + '" data-lit="' +
      (held[index] === true || (all && Boolean(cell))) + '" title="' +
      esc(longDate(iso) + (cell ? " · " + shift.name + " · " + cell.role
        : " · off duty")) + '"><i>' + isoDate(iso).getDate() + "</i>" +
      (cell ? esc(cell.shift) : "·") + "</span>";
  }).join("");
  const hurt = (out.violations_by_employee || {})[id] || [];
  const labels = {};
  inst.rules.forEach(rule => { labels[rule.id] = rule.label; });
  return '<div class="slip card"><h3>' + esc(id + " · " + (stats.name || "")) +
    "</h3>" + '<p class="note">Holds <b>' +
    esc((stats.roles || []).join(", ") || "no role") + "</b>" +
    (who.contract ? " · " + esc(who.contract) : "") + " · longest run <b>" +
    num(stats.longest_run || 0) + "</b> days · " +
    esc(inst.shifts.map(shift => shift.name + " " +
      num((stats.by_shift || {})[shift.id] || 0)).join(" · ")) + "</p>" +
    tally([["duties", num(stats.duties || 0)], ["hours", num(stats.hours || 0)],
           ["nights", num(stats.nights || 0)],
           ["weekends worked", num(stats.weekends || 0)]]) +
    '<div class="strip">' + strip + "</div>" +
    (hurt.length
      ? ledger(hurt.slice(0, 8).map(one => [
          one.severity === "hard" ? "hard" : "soft",
          (labels[one.rule_id] || one.rule_id) + " · " + one.message,
          one.severity === "hard" ? "bad" : ""]))
      : ledger([["nothing given up", "no rule was broken for this person"]])) +
    (hurt.length > 8
      ? '<p class="key">and ' + (hurt.length - 8) + " more against this person</p>"
      : "") +
    '<div class="doing">' + press("Close", "who", true, false, id) + "</div></div>";
}

function rosterPanel() {
  if (!state.instance) return nothingYet("There is no month to roster yet.",
                                         OPEN_IT, "sample");
  const out = state.solved;
  if (!out) {
    return '<div class="empty"><p>The engine covers every duty first, then spends ' +
      "whatever time it is given trading the soft rules against each other — the " +
      "fairness of the spread, nights, weekends, requests — and reports exactly " +
      "what it gave up.</p>" + budget() +
      press(state.busy ? "Searching…" : "Generate the roster", "solve", false,
            state.busy) + "</div>";
  }
  const score = out.score;
  return (state.dirty ? '<p class="warn">The rule set has changed since this ' +
      "roster was generated — generate it again.</p>" : "") +
    tally([[score.feasible ? "legal roster" : "not a legal roster",
                 score.feasible ? "Yes" : "No"],
                ["hard breaches", score.hard_violations],
                ["soft penalty", num(score.cost)],
                ["busiest minus quietest", out.spread.duties + " duties"]]) +
    budget() +
    press(state.busy ? "Searching…" : "Generate again", "solve", true, state.busy) +
    '<p class="readout" role="status" aria-live="polite">' + esc(HINT) + "</p>" +
    sift(out) +
    grid(out) +
    personCard(out) +
    ledger([
      ["Search", out.search.engine + " · seed " + out.search.options.seed],
      ["Time", num(out.search.seconds) + "s over " +
               out.search.iterations.toLocaleString() + " moves"],
      ["Cost", "started at " + num(out.search.construction_cost) + ", ended at " +
               num(out.search.cost)],
      ["Coverage", out.coverage.under + " duties short · " + out.coverage.over +
                   " overstaffed"],
      ["Spread", "duties " + out.spread.duties + " · nights " + out.spread.nights +
                 " · weekends " + out.spread.weekends + " · hours " +
                 num(out.spread.hours)]
    ]) +
    breaches(out);
}

const PANELS = { period: periodPanel, staff: staffPanel, shifts: shiftsPanel,
                 rules: rulesPanel, check: checkPanel, roster: rosterPanel };

function heldBy(node) {
  if (!node || !node.dataset) return "";
  if (node.dataset.do) {
    return 'button[data-do="' + node.dataset.do + '"]' +
      (/^[\w.:-]+$/.test(node.dataset.id || "")
        ? '[data-id="' + node.dataset.id + '"]' : "");
  }
  if (!node.dataset.set) return "";
  const set = node.dataset.set;
  return '[data-set="' + set + '"]' +
    (node.dataset.name ? '[data-name="' + node.dataset.name + '"]' : "") +
    (set === "pick" || set === "hold" ? '[value="' + node.value + '"]' : "");
}

function render() {
  const held = heldBy(document.activeElement);
  Object.keys(PANELS).forEach(name => {
    panel(name).innerHTML = PANELS[name]();
    at("s-" + name).hidden = name !== state.step;
  });
  document.querySelectorAll("#stub button").forEach(button => {
    button.disabled = !state.instance && button.dataset.go !== "period";
    button.setAttribute("aria-current", String(button.dataset.go === state.step));
  });
  if (held) {
    try {
      const again = at("s-" + state.step).querySelector(held);
      if (again) again.focus();
    } catch (err) {
      return;
    }
  }
}

function goTo(name) {
  if (!PANELS[name]) return;
  state.step = name;
  render();
}
async function checkEngine() {
  at("lamp").dataset.state = "";
  at("wire").textContent = "asking the engine…";
  try {
    const health = await api("/health");
    state.health = health;
    at("lamp").dataset.state = "ready";
    at("wire").textContent = health.rule_types + " kinds of rule · " +
      health.endpoints.length + " endpoints · " +
      (health.authenticated ? "token required" : "no token, loopback only");
  } catch (err) {
    state.health = null;
    state.schema = null;
    at("lamp").dataset.state = "down";
    at("wire").textContent = err.message;
    render();
    return;
  }
  try {
    state.schema = await api("/schema");
  } catch (err) {
    state.schema = null;
  }
  render();
}

async function loadSample() {
  say("Fetching the sample month…", "");
  try {
    const out = await api("/sample");
    state.instance = out.instance;
    state.check = null;
    state.solved = null;
    state.draft = null;
    state.dropped = null;
    state.dirty = false;
    state.edit = null;
    state.gone = null;
    state.pick = "";
    state.pickFind = "";
    state.staffFind = "";
    state.lit = "";
    state.who = "";
    render();
    say(state.instance.employees.length + " staff over " +
        state.instance.horizon.num_days + " days.",
        "Steps 2 to 4 read it back. Step 5 asks whether the month is possible, " +
        "step 6 builds it.");
  } catch (err) {
    say("Could not open the sample month.", err.message, "bad");
  }
}

async function runCheck() {
  if (!state.instance) return;
  say("Weighing the demand against the staff…", "");
  try {
    const out = await api("/validate", { instance: state.instance });
    state.check = out;
    render();
    say(out.ok ? "This month is workable." : "This month cannot work as it stands.",
        out.ok ? "Nothing impossible found before the search starts."
               : out.problems.length + " named on step 5.",
        out.ok ? "" : "bad");
  } catch (err) {
    say("The check did not run.", err.message, "bad");
  }
}

async function runSolve() {
  if (!state.instance || state.busy) return;
  state.busy = true;
  state.seed += 1;
  render();
  const began = Date.now();
  const counting = setInterval(() => {
    say("Searching… " + Math.round((Date.now() - began) / 1000) + "s of about " +
        state.seconds + ".", "Every duty is covered first, then the soft rules " +
        "are traded against each other.");
  }, 1000);
  try {
    const out = await api("/solve", {
      instance: state.instance,
      options: { seed: state.seed, max_seconds: state.seconds }
    });
    state.solved = out;
    state.dirty = false;
    state.lit = "";
    state.who = "";
    render();
    const score = out.score;
    say(score.feasible ? "A legal roster." : "No legal roster yet.",
        score.hard_violations + " hard, " + score.soft_violations +
        " soft · penalty " + num(score.cost) + " · " + num(out.search.seconds) +
        "s · seed " + out.search.options.seed,
        score.feasible ? "" : "bad");
  } catch (err) {
    say("The search did not run.", err.message, "bad");
  } finally {
    clearInterval(counting);
    state.busy = false;
    render();
  }
}

function plainly(err) {
  let why = String(err.message || err).replace(/ \(instance[^)]*\)$/, "");
  why = why.replace(/^(rule|instance) rejected: /, "");
  if (state.draft) {
    // the slip already says which rule this is, so drop the engine's own preamble
    why = why.replace(new RegExp("^rule \\S+ \\(" + state.draft.type + "\\): "), "");
  }
  return why;
}

async function commit(patch, told, fresh) {
  const trial = Object.assign({}, state.instance, patch);
  const had = Boolean(state.solved);
  state.busy = true;
  render();
  try {
    const out = await api("/validate", { instance: trial });
    state.instance = trial;
    state.check = out;
    state.draft = null;
    state.edit = null;
    if (fresh) {
      state.solved = null;
      state.lit = "";
      state.who = "";
      state.dirty = false;
    } else state.dirty = had;
    say(told, (out.ok
      ? trial.rules.length + " rules over " + trial.employees.length +
        " staff, and the month still works."
      : out.problems.length + " problem(s) — see step 5.") +
      (fresh && had ? " The roster was built for the month as it was, so it has " +
        "been cleared — generate it again on step 6." : ""),
      out.ok ? "" : "bad");
    return true;
  } catch (err) {
    if (state.draft) state.draft.error = plainly(err);
    if (state.edit) state.edit.error = plainly(err);
    say("The engine would not take that.", plainly(err), "bad");
    return false;
  } finally {
    state.busy = false;
    render();
  }
}

function firstType() {
  const first = families()[0];
  return first ? first[1][0].type : "";
}

function startDraft() {
  const type = firstType();
  if (!type) return;
  state.draft = blankDraft(type);
  render();
}

function editRule(id) {
  const found = state.instance.rules.filter(rule => rule.id === id)[0];
  if (!found) return;
  const draft = blankDraft(found.type);
  draft.editing = id;
  draft.severity = found.severity;
  draft.weight = found.weight;
  draft.label = found.label || "";
  draft.scope = { kind: (found.scope && found.scope.kind) || "all",
                  ids: ((found.scope && found.scope.ids) || []).slice() };
  Object.keys(found.params || {}).forEach(name => {
    const value = found.params[name];
    draft.params[name] = Array.isArray(value) ? value.slice() : value;
  });
  state.draft = draft;
  render();
}

async function saveRule() {
  const draft = state.draft;
  if (!draft || state.busy) return;
  const card = typeCard(draft.type);
  const missing = (card ? card.params : []).filter(param =>
    param.required && blank(draft.params[param.name]));
  if (missing.length) {
    draft.error = "Still to fill in: " +
      missing.map(param => param.label.replace(/ *\(.*\)$/, "")).join(", ") + ".";
    render();
    return;
  }
  if (draft.scope.kind !== "all" && !draft.scope.ids.length) {
    draft.error = "Choose who this applies to, or set it back to everyone.";
    render();
    return;
  }
  const rule = {
    id: draft.editing || freshId(draft.type),
    type: draft.type,
    severity: draft.severity,
    weight: draft.severity === "hard" ? 1 : (Number(draft.weight) || 1),
    scope: { kind: draft.scope.kind, ids: draft.scope.ids.slice() },
    params: tidyParams(card, draft.params),
    label: (draft.label || "").trim() || autoLabel(draft)
  };
  const rules = state.instance.rules.slice();
  const found = rules.map(one => one.id).indexOf(rule.id);
  if (found >= 0) rules[found] = rule; else rules.push(rule);
  draft.error = "";
  const from = draft.fromLine;
  if (await commit({ rules: rules },
                   (found >= 0 ? "Saved: " : "Added: ") + rule.label) && from) {
    forget(from);
    render();
  }
}

async function dropRule(id) {
  const gone = state.instance.rules.filter(rule => rule.id === id)[0];
  if (!gone || state.busy) return;
  const kept = state.instance.rules.filter(rule => rule.id !== id);
  if (await commit({ rules: kept }, "Dropped: " + gone.label)) {
    state.dropped = gone;
    render();
  }
}

async function undrop() {
  const back = state.dropped;
  if (!back || state.busy) return;
  state.dropped = null;
  if (!await commit({ rules: state.instance.rules.concat([back]) },
                    "Put back: " + back.label)) {
    state.dropped = back;
  }
  render();
}

function renamedFor(name, span) {
  const stem = /^(.*)-\d{4}-\d\d-\d\d-\d+d$/.exec(name || "");
  return stem ? stem[1] + "-" + span.start + "-" + span.num_days + "d" : name;
}

async function savePeriod() {
  const edit = state.edit;
  const trial = periodTrial();
  if (!edit || !trial || state.busy) return;
  const lost = trial.rules.lost;
  edit.error = "";
  await commit({ horizon: trial.span,
                 demand: trial.demand.demand,
                 rules: trial.rules.rules,
                 name: renamedFor(state.instance.name, trial.span) },
    "The month now runs from " + longDate(trial.span.start) + " for " +
    trial.span.num_days + " days." + (lost.length ? " " + lost.length +
      " dated rule(s) fell outside it and went with the old dates: " +
      lost.map(rule => rule.label).join("; ") : ""), true);
}

function openEdit(kind, id) {
  const inst = state.instance;
  if (!inst || state.busy) return;
  if (kind === "period") state.edit = { kind: "period", start: inst.horizon.start,
                                        days: String(inst.horizon.num_days),
                                        error: "" };
  if (kind === "person") {
    const person = id ? inst.employees.filter(one => one.id === id)[0] : null;
    if (id && !person) return;
    state.edit = personEdit(person);
  }
  if (kind === "shift") {
    const shift = inst.shifts.filter(one => one.id === id)[0];
    if (!shift) return;
    state.edit = shiftEdit(shift);
  }
  render();
}

async function savePerson() {
  const edit = state.edit;
  const inst = state.instance;
  if (!edit || !inst || state.busy) return;
  const id = (edit.id || "").trim();
  const name = (edit.name || "").trim();
  const stop = word => { edit.error = word; render(); };
  if (!/^[A-Za-z0-9_.:-]+$/.test(id)) {
    return stop("A staff number can hold letters, digits and - _ . : — nothing " +
                "else, because every rule names the person by it.");
  }
  if (id !== edit.was && inst.employees.some(one => one.id === id)) {
    return stop(id + " is already on the roll.");
  }
  if (!edit.roles.length) {
    return stop("Choose at least one role, or there is no duty this person could " +
                "be given.");
  }
  const person = { id: id, name: name || id, roles: edit.roles.slice(),
                   contract: (edit.contract || "").trim() || "permanent" };
  const patch = { employees: edit.was
    ? inst.employees.map(one => one.id === edit.was ? person : one)
    : inst.employees.concat([person]) };
  if (edit.was && id !== edit.was) {
    const tied = scopeRules(inst, edit.was).length;
    patch.rules = renameInRules(inst, edit.was, id);
    edit.renamed = tied;
  }
  edit.error = "";
  const was = edit.was;
  if (await commit(patch, (was ? "Saved " + id : "Added " + id + " to the roll") +
      (was && id !== was ? ", and rewrote " + edit.renamed + " rule(s) that named " +
        was : ""), true)) {
    if (state.pick === was) state.pick = id;
    render();
  }
}

async function removePerson(id) {
  const inst = state.instance;
  if (!inst || state.busy) return;
  const person = inst.employees.filter(one => one.id === id)[0];
  if (!person) return;
  if (inst.employees.length < 2) {
    say("The roll cannot be emptied.", "A month needs somebody to work it.", "bad");
    return;
  }
  const out = withoutPerson(inst, id);
  const gone = { person: person, at: inst.employees.indexOf(person),
                 lost: out.lost, trimmed: out.trimmed };
  if (await commit({ employees: out.employees, rules: out.rules },
      "Removed " + id + " · " + (person.name || id) + (out.lost.length
        ? ", and with them " + out.lost.length + " rule(s) that named nobody else: " +
          out.lost.map(rule => rule.label).join("; ")
        : ""), true)) {
    state.gone = gone;
    if (state.pick === id) state.pick = "";
    render();
  }
}

async function unremove() {
  const back = state.gone;
  const inst = state.instance;
  if (!back || !inst || state.busy) return;
  const id = back.person.id;
  const employees = inst.employees.slice();
  employees.splice(Math.min(back.at, employees.length), 0, back.person);
  const held = {};
  back.trimmed.forEach(one => { held[one] = true; });
  const seen = taken();
  const rules = inst.rules.map(rule => held[rule.id]
    ? Object.assign({}, rule, { scope: { kind: "employees",
        ids: (rule.scope.ids || []).concat([id]).slice().sort() } })
    : rule).concat(back.lost.filter(rule => !seen[rule.id]));
  state.gone = null;
  if (!await commit({ employees: employees, rules: rules },
                    "Put " + id + " back on the roll", true)) {
    state.gone = back;
  }
  render();
}

async function saveShift() {
  const edit = state.edit;
  const inst = state.instance;
  const trial = edit ? shiftTrial() : null;
  if (!edit || !inst || !trial || state.busy) return;
  edit.error = "";
  const shifts = inst.shifts.map(shift => shift.id === edit.id
    ? Object.assign({}, shift, { name: (edit.name || "").trim() || shift.id,
        start_min: trial.start_min, duration_min: trial.duration_min,
        counts_as_night: Boolean(edit.night) })
    : shift);
  await commit({ shifts: shifts }, edit.id + " now runs " +
    clock(trial.start_min) + "–" + clock(trial.start_min + trial.duration_min) +
    " · " + hours(trial.duration_min) +
    (edit.night ? " · counts as a night" : ""), true);
}

function pickWho(id) {
  state.pick = state.pick === id ? "" : id;
  render();
}

async function readMemo() {
  const text = state.memoText.trim();
  if (state.busy) return;
  if (!text) {
    state.readError = "Paste the wording first, one rule to a line.";
    render();
    return;
  }
  state.busy = true;
  state.readError = "";
  render();
  try {
    const out = await api("/parse", { text: text, instance: state.instance });
    state.read = out;
    const counts = out.counts;
    say(counts.drafted + " of " + counts.statements + " statements read.",
        counts.unparsed
          ? counts.unparsed + " could not be read — the reason is beside each one."
          : "Accept the ones the officials meant.",
        counts.unparsed ? "bad" : "");
  } catch (err) {
    state.readError = plainly(err);
    say("The engine could not read that.", plainly(err), "bad");
  } finally {
    state.busy = false;
    render();
  }
}

function forget(line) {
  if (!state.read) return;
  state.read.drafts = state.read.drafts.filter(one => one.line !== line);
}

function asRule(rule, seen) {
  const id = rule.id && !seen[rule.id] ? rule.id : freshId(rule.type, seen);
  seen[id] = true;
  return {
    id: id,
    type: rule.type,
    severity: rule.severity,
    weight: rule.severity === "hard" ? 1 : (Number(rule.weight) || 1),
    scope: { kind: (rule.scope && rule.scope.kind) || "all",
             ids: ((rule.scope && rule.scope.ids) || []).slice() },
    params: rule.params || {},
    label: (rule.label || "").trim() || rule.type
  };
}

async function takeDraft(line) {
  const found = proposalOn(line);
  if (!found || !found.rule || state.busy) return;
  const rule = asRule(found.rule, taken());
  if (await commit({ rules: state.instance.rules.concat([rule]) },
                   "Accepted: " + rule.label)) {
    forget(line);
    render();
  }
}

async function takeAll() {
  const ready = drafted();
  if (!ready.length || state.busy) return;
  const seen = taken();
  const rules = ready.map(one => asRule(one.rule, seen));
  if (await commit({ rules: state.instance.rules.concat(rules) },
                   "Accepted " + rules.length + " proposals.")) {
    ready.forEach(one => forget(one.line));
    render();
  }
}

function slipFrom(line) {
  const found = proposalOn(line);
  if (!found || state.busy) return;
  const rule = found.rule;
  const suggested = (found.suggestions || []).filter(type => typeCard(type))[0];
  const type = rule ? rule.type : (suggested || firstType());
  if (!type) return;
  const draft = blankDraft(type);
  draft.fromLine = line;
  draft.label = ((rule && rule.label) || found.text || "").trim();
  if (rule) {
    draft.severity = rule.severity;
    if (rule.severity === "soft") draft.weight = rule.weight;
    draft.scope = { kind: (rule.scope && rule.scope.kind) || "all",
                    ids: ((rule.scope && rule.scope.ids) || []).slice() };
    Object.keys(rule.params || {}).forEach(name => {
      const value = rule.params[name];
      draft.params[name] = Array.isArray(value) ? value.slice() : value;
    });
  } else {
    draft.error = "Nothing was read from this line, so nothing is filled in but " +
      "the wording. Set it out by hand.";
  }
  state.draft = draft;
  render();
}

function skipDraft(line) {
  const found = proposalOn(line);
  if (!found || state.busy) return;
  if (state.draft && state.draft.fromLine === line) state.draft = null;
  forget(line);
  say("Discarded: " + found.text, "Nothing in the month changed.");
  render();
}

function readout(text, tone) {
  const note = document.querySelector(".readout");
  if (!note) return;
  note.textContent = text || HINT;
  note.dataset.tone = tone || "";
}

function crosshair(cell) {
  const roll = document.querySelector(".roll");
  if (!roll || !roll.querySelectorAll) return;
  Array.prototype.forEach.call(roll.querySelectorAll(".col"),
                               node => node.classList.remove("col"));
  const day = cell && cell.dataset ? cell.dataset.day : undefined;
  if (day === undefined) return;
  Array.prototype.forEach.call(roll.querySelectorAll('[data-day="' + day + '"]'),
                               node => node.classList.add("col"));
}

function lightUp(id) {
  const out = state.solved;
  if (!out) return;
  state.lit = state.lit === id ? "" : id;
  render();
  if (!state.lit) {
    readout("");
    return;
  }
  const rule = state.instance.rules.filter(one => one.id === id)[0] || {};
  const label = rule.label || id;
  const mark = litDuties(out);
  const days = Object.keys(mark.days).length;
  if (mark.month || (!mark.people && !days)) {
    readout(label + " — this breach is about the month as a whole, not any " +
            "particular duty, so nothing is marked on the sheet.");
    return;
  }
  const held = Object.keys(mark.cells);
  const whole = Object.keys(mark.rows).length;
  const duties = held.reduce((sum, who) => sum + Object.keys(mark.cells[who]).length, 0);
  const parts = [];
  if (duties) {
    parts.push(duties + (duties === 1 ? " duty" : " duties") + " held by " +
               held.length + (held.length === 1 ? " person" : " people"));
  }
  if (whole) {
    parts.push("every duty held by " + whole + (whole === 1 ? " person" : " people"));
  }
  if (days) parts.push(days + (days === 1 ? " day" : " days") + " at the head of the sheet");
  const first = document.querySelector('.roll [data-lit="true"]');
  readout(label + " — marked in red: " + parts.join(" · ") +
          (first ? "." : ", but the sheet is filtered and none of them are showing."),
          "bad");
  const seek = document.querySelector(".roll td.lit");
  if (seek && seek.scrollIntoView) {
    seek.scrollIntoView({ block: "center", inline: "center" });
  }
}

function showWho(id) {
  if (!state.solved) return;
  state.who = state.who === id ? "" : id;
  render();
  const card = document.querySelector(".card");
  if (state.who && card && card.scrollIntoView) {
    card.scrollIntoView({ block: "nearest" });
  }
}

at("stub").addEventListener("click", event => {
  const button = event.target.closest("button[data-go]");
  if (button && !button.disabled) goTo(button.dataset.go);
});

function setField(what, value, name, on) {
  if (what === "seconds") {
    state.seconds = Number(value);
    return false;
  }
  if (what === "memo") {
    state.memoText = value;
    return false;
  }
  if (what === "find") {
    state.view.find = value;
    return true;
  }
  if (what === "role") {
    state.view.role = value;
    return true;
  }
  if (what === "only") {
    state.view.only = Boolean(on);
    return true;
  }
  if (what === "staff-find") {
    state.staffFind = value;
    return true;
  }
  if (what === "pick-find") {
    state.pickFind = value;
    return true;
  }
  if (what === "edit" || what === "edit-flag" || what === "hold") {
    const edit = state.edit;
    if (!edit) return false;
    edit.error = "";
    if (what === "edit") edit[name] = value;
    else if (what === "edit-flag") edit[name] = Boolean(on);
    else {
      edit.roles = on ? edit.roles.concat([value]).sort()
                      : edit.roles.filter(one => one !== value);
    }
    return true;
  }
  const draft = state.draft;
  if (!draft) return false;
  if (what === "type") {
    const kept = draft.editing;
    const from = draft.fromLine;
    state.draft = blankDraft(value);
    state.draft.editing = kept;
    state.draft.fromLine = from;
    return true;
  }
  if (what === "severity") { draft.severity = value; return true; }
  if (what === "weight") { draft.weight = value; return false; }
  if (what === "label") { draft.label = value; return false; }
  if (what === "scope-kind") {
    draft.scope = { kind: value, ids: [] };
    return true;
  }
  if (what === "scope-ids") { draft.scope.ids = value; return false; }
  if (what === "flag") { draft.params[name] = Boolean(on); return true; }
  if (what === "param") { draft.params[name] = value; return false; }
  if (what === "pick") {
    const held = draft.params[name] || [];
    draft.params[name] = on ? held.concat([value]).sort()
                            : held.filter(one => one !== value);
    return true;
  }
  return false;
}

document.querySelector(".sheet").addEventListener("change", event => {
  const field = event.target.closest("[data-set]");
  if (!field) return;
  const many = field.dataset.set === "scope-ids";
  const value = many
    ? Array.prototype.slice.call(field.selectedOptions || []).map(one => one.value)
    : field.value;
  if (setField(field.dataset.set, value, field.dataset.name, field.checked)) render();
});

const LIVE = ["find", "staff-find", "pick-find"];

document.querySelector(".sheet").addEventListener("input", event => {
  const memo = event.target.closest('[data-set="memo"]');
  if (memo) {
    state.memoText = memo.value;
    return;
  }
  const field = event.target.closest("[data-set]");
  if (!field || LIVE.indexOf(field.dataset.set) < 0) return;
  const what = field.dataset.set;
  const caret = field.selectionStart;
  if (!setField(what, field.value, field.dataset.name, field.checked)) return;
  render();
  const again = document.querySelector('[data-set="' + what + '"]');
  if (again && again.setSelectionRange) {
    again.focus();
    again.setSelectionRange(caret, caret);
  }
});

document.querySelector(".sheet").addEventListener("mouseover", event => {
  const cell = event.target.closest("[data-say]");
  crosshair(cell);
  if (cell) readout(cell.dataset.say);
});

document.querySelector(".sheet").addEventListener("focusin", event => {
  const cell = event.target.closest("[data-say]");
  if (cell) readout(cell.dataset.say);
});

document.querySelector(".sheet").addEventListener("click", event => {
  const button = event.target.closest("button[data-do]");
  if (!button || button.disabled) return;
  const doing = button.dataset.do;
  if (doing === "sample") loadSample();
  if (doing === "check") runCheck();
  if (doing === "solve") runSolve();
  if (doing === "add-rule") startDraft();
  if (doing === "cancel-rule") { state.draft = null; render(); }
  if (doing === "save-rule") saveRule();
  if (doing === "edit-rule") editRule(button.dataset.id);
  if (doing === "drop-rule") dropRule(button.dataset.id);
  if (doing === "undrop") undrop();
  if (doing === "memo") { state.memo = !state.memo; render(); }
  if (doing === "read-memo") readMemo();
  if (doing === "take-draft") takeDraft(Number(button.dataset.id));
  if (doing === "take-all") takeAll();
  if (doing === "open-draft") slipFrom(Number(button.dataset.id));
  if (doing === "skip-draft") skipDraft(Number(button.dataset.id));
  if (doing === "light") lightUp(button.dataset.id);
  if (doing === "who") showWho(button.dataset.id);
  if (doing === "edit-period") openEdit("period");
  if (doing === "save-period") savePeriod();
  if (doing === "add-person") openEdit("person", "");
  if (doing === "edit-person") openEdit("person", button.dataset.id);
  if (doing === "save-person") savePerson();
  if (doing === "drop-person") removePerson(button.dataset.id);
  if (doing === "unremove") unremove();
  if (doing === "edit-shift") openEdit("shift", button.dataset.id);
  if (doing === "save-shift") saveShift();
  if (doing === "cancel-edit") { state.edit = null; render(); }
  if (doing === "pick") pickWho(button.dataset.id);
});

at("recheck").addEventListener("click", checkEngine);
render();
checkEngine();
