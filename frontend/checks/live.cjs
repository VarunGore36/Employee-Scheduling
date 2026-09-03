// Drives the real page code against a running engine: node checks/live.cjs
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
const PORT = process.env.PORT || "8000";

function elem(key) {
  return { key, dataset: {}, textContent: "", innerHTML: "", hidden: false,
           disabled: false, attrs: {},
           setAttribute(name, value) { this.attrs[name] = value; },
           addEventListener() {}, closest() { return null; },
           querySelector() { return null; },
           focus() { document.activeElement = this; } };
}
const nodes = {};
const pick = key => (nodes[key] = nodes[key] || elem(key));
const stubs = ["period", "staff", "shifts", "rules", "check", "roster"].map(go => {
  const node = pick("stub:" + go); node.dataset.go = go; return node;
});
const document = {
  activeElement: null,
  getElementById: pick,
  querySelector: pick,
  querySelectorAll: sel => (sel === "#stub button" ? stubs : [])
};
const location = { protocol: "file:", search: "" };
const asked = [];

async function fetcher(url, opts) {
  asked.push(url.replace("http://127.0.0.1:8000", "") +
             (opts && opts.method === "POST" ? " (post)" : ""));
  const reply = await fetch(url.replace("127.0.0.1:8000", "127.0.0.1:" + PORT), opts)
    .catch(() => { throw new Error("no engine on port " + PORT +
      " — start it with: python -m roster.cli serve --port " + PORT); });
  return reply;
}

const app = new Function("document", "location", "fetch", src + "\nreturn {" +
  "state, render, checkEngine, loadSample, runCheck, runSolve, savePeriod," +
  "savePerson, removePerson, unremove, saveShift, setField, openEdit, pickWho," +
  "periodTrial, shiftTrial, personEdit, shiftEdit, dutiesFor, marksFor};")(
  document, location, fetcher);

const fill = name => nodes['[data-fill="' + name + '"]'].innerHTML;
const count = (text, pattern) => (text.match(pattern) || []).length;
let failures = 0;
function ok(label, condition, extra) {
  if (!condition) { failures++; console.log("FAIL  " + label, extra || ""); }
  else console.log("ok    " + label);
}
const wire = () => nodes.wire.textContent;
const tick = () => nodes.tick.textContent;

async function main() {
  await app.checkEngine();
  ok("the page finds the real engine and reads its rule catalogue",
     nodes.lamp.dataset.state === "ready" && app.state.schema &&
     app.state.schema.rule_types.length > 0, wire());
  if (nodes.lamp.dataset.state !== "ready") {
    throw new Error("nothing is answering on port " + PORT +
      " — start it with: python -m roster.cli serve --port " + PORT);
  }

  await app.loadSample();
  const inst = app.state.instance;
  ok("the sample month comes down whole",
     inst && inst.employees.length === 44 && inst.horizon.start === "2026-09-12" &&
     inst.horizon.num_days === 31 && inst.rules.length === 33, wire());
  ok("opening it leaves the verdict to step 5 rather than assuming one",
     app.state.check === null && app.state.solved === null);
  await app.runCheck();
  ok("and the engine calls the month as loaded workable",
     app.state.check.ok === true,
     JSON.stringify((app.state.check || {}).problems || []).slice(0, 200));

  await app.savePeriod();
  ok("nothing is sent while no month change is open", app.state.edit === null);

  app.openEdit("period", "");
  app.setField("edit", "2026-10-01", "start");
  app.setField("edit", "30", "days");
  const trial = app.periodTrial();
  ok("the page works out the move itself before asking",
     trial && trial.delta === 19 && trial.rules.lost.length === 0 &&
     trial.demand.demand.length === 240 && trial.demand.laid === true,
     trial && JSON.stringify({ d: trial.delta, lost: trial.rules.lost.length }));
  await app.savePeriod();
  const moved = app.state.instance;
  ok("the real engine accepts the moved month",
     moved.horizon.start === "2026-10-01" && moved.horizon.num_days === 30 &&
     moved.demand.length === 240 && moved.rules.length === 33 &&
     app.state.edit === null, tick());
  ok("every dated rule came with it",
     moved.rules.filter(r => r.id === "leave1")[0].params.days[0] === "2026-10-02" &&
     moved.rules.filter(r => r.id === "fixed1")[0].params.day === "2026-10-05");
  ok("the month is renamed after the dates it now covers",
     moved.name === "university-2026-10-01-30d");

  await app.runCheck();
  ok("the engine still calls the moved month workable",
     app.state.check.ok === true,
     JSON.stringify(app.state.check.problems || []).slice(0, 200));

  app.openEdit("person", "E24");
  app.setField("edit", "E88", "id");
  app.setField("edit", "Renamed Person", "name");
  await app.savePerson();
  const renamed = app.state.instance;
  ok("the real engine accepts a renamed person with the rules rewritten to match",
     renamed.employees[23].id === "E88" &&
     renamed.employees[23].name === "Renamed Person" &&
     renamed.rules.filter(r => r.id === "leave1")[0].scope.ids.join(",") === "E88",
     tick());

  app.openEdit("person", "");
  const fresh = app.state.edit.id;
  app.setField("hold", "MTS", "roles", true);
  await app.savePerson();
  ok("a new hand is taken on",
     app.state.instance.employees.length === 45 &&
     app.state.instance.employees[44].id === fresh, tick());

  await app.removePerson(fresh);
  ok("and can be taken off again",
     app.state.instance.employees.length === 44 &&
     !app.state.instance.employees.some(one => one.id === fresh), tick());

  await app.removePerson("E88");
  const short = app.state.instance;
  ok("removing a person the rules name drops those rules with them",
     short.employees.length === 43 && short.rules.length === 31 &&
     !short.rules.some(r => r.id === "leave1"), tick());
  await app.unremove();
  ok("and putting them back restores the person and the rules",
     app.state.instance.employees.length === 44 &&
     app.state.instance.employees[23].id === "E88" &&
     app.state.instance.rules.length === 33, tick());

  app.openEdit("shift", "M");
  app.setField("edit", "07:30", "start");
  app.setField("edit", "9.5", "hours");
  ok("the new clock is worked out before it is sent",
     JSON.stringify(app.shiftTrial()) === '{"start_min":450,"duration_min":570}');
  await app.saveShift();
  ok("the real engine accepts the new shift clock",
     app.state.instance.shifts[0].start_min === 450 &&
     app.state.instance.shifts[0].duration_min === 570 &&
     app.state.instance.shifts[0].id === "M", tick());

  app.openEdit("shift", "E");
  app.setField("edit-flag", "", "night", true);
  await app.saveShift();
  ok("and a shift newly counted as a night",
     app.state.instance.shifts[1].counts_as_night === true, tick());

  app.openEdit("shift", "E");
  app.setField("edit-flag", "", "night", false);
  await app.saveShift();
  app.openEdit("shift", "M");
  app.setField("edit", "06:00", "start");
  app.setField("edit", "8", "hours");
  await app.saveShift();
  ok("the shifts are put back as they were",
     app.state.instance.shifts[0].start_min === 360 &&
     app.state.instance.shifts[1].counts_as_night === false);

  app.openEdit("shift", "M");
  app.setField("edit", "06:00", "start");
  app.setField("edit", "0.1", "hours");
  const before = asked.length;
  await app.saveShift();
  ok("an impossible length never reaches the engine",
     asked.length === before && app.state.instance.shifts[0].duration_min === 480);
  app.state.edit = null;

  app.state.instance.shifts[0].duration_min = 0;
  await app.runCheck();
  ok("and if one got through, the real engine refuses it in its own words",
     nodes.tock.textContent.includes("duration_min must be in 1..1440"),
     tick() + " / " + nodes.tock.textContent);
  app.state.instance.shifts[0].duration_min = 480;

  app.setField("secs", "20", "");
  await app.runSolve();
  const out = app.state.solved;
  ok("the edited month solves on the real engine",
     out && out.score.feasible === true && out.score.hard_violations === 0 &&
     out.roster.rows.length === 44 && out.roster.dates.length === 30,
     out ? JSON.stringify(out.score) : "no answer");
  ok("the roster the engine sends back covers the month the page asked for",
     out.roster.dates[0] === "2026-10-01" && out.roster.dates[29] === "2026-10-30");

  app.pickWho("E88");
  const card = fill("shifts");
  const duties = app.dutiesFor("E88");
  ok("the renamed person's own month reads off the real roster",
     card.includes("<h4>E88 · Renamed Person</h4>") && card.includes('class="cal"') &&
     Object.keys(duties).length > 0 && !card.includes("No roster has been generated"),
     Object.keys(duties || {}).length + " duties");
  ok("their calendar counts the same duties the engine reported",
     count(card, /<td class="[^"]*\bon\b/g) === Object.keys(duties).length);
  ok("the leave the rules fix for them is printed on the days it covers",
     count(card, /class="mark firm">away</g) === 7,
     count(card, /class="mark firm">away</g));
  ok("every duty on the calendar sits inside the month",
     Object.keys(duties).every(iso => iso >= "2026-10-01" && iso <= "2026-10-30"));
  ok("no duty falls on a day their leave covers",
     Object.keys(app.marksFor(app.state.instance,
       app.state.instance.employees[23]).filter ? {} : {}) !== null &&
     !Object.keys(duties).some(iso => iso >= "2026-10-02" && iso <= "2026-10-08"),
     Object.keys(duties).filter(iso => iso >= "2026-10-02" && iso <= "2026-10-08")
       .join(","));

  console.log("\ncalls made: " + asked.join(", "));
  console.log(failures ? "\n" + failures + " live check(s) failed"
                       : "\nall live checks pass");
  process.exit(failures ? 1 : 0);
}
main().catch(err => {
  console.log("\n" + err.message);
  process.exit(1);
});
