// Builds a month from nothing with the real page code against a running
// engine: node checks/live.cjs
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
  "state, render, checkEngine, runCheck, runSolve, setField, openEdit, pickWho," +
  "startTrial, startMonth, saveRole, removeRole, saveShift, removeShift," +
  "savePerson, removePerson, unremove, saveDemand, demandTrial, savePeriod," +
  "periodTrial, shiftTrial, startDraft, saveRule, ready, stillNeeds," +
  "dutiesFor, marksFor};")(document, location, fetcher);

const fill = name => nodes['[data-fill="' + name + '"]'].innerHTML;
const count = (text, pattern) => (text.match(pattern) || []).length;
let failures = 0;
function ok(label, condition, extra) {
  if (!condition) { failures++; console.log("FAIL  " + label, extra || ""); }
  else console.log("ok    " + label);
}
const wire = () => nodes.wire.textContent;
const tick = () => nodes.tick.textContent;
const tock = () => nodes.tock.textContent;
const posts = () => asked.filter(one => one.indexOf("(post)") > 0).length;

const ROLES = [["DSG", "Daily Support Grade"], ["LSG", "Late Support Grade"],
               ["MTS", "Medical Technical Staff"]];
const SHIFTS = [["M", "Morning", "06:00", "8", false],
                ["E", "Evening", "14:00", "8", false],
                ["N", "Night", "22:00", "8", true]];
const ROLL = [["1001", ["DSG", "LSG"]], ["1002", ["DSG", "LSG"]],
              ["1003", ["DSG", "LSG"]], ["1004", ["DSG", "MTS"]],
              ["1005", ["DSG", "MTS"]], ["1006", ["DSG", "MTS"]],
              ["1007", ["DSG"]], ["1008", ["DSG"]], ["1009", ["DSG"]]];

async function addPerson(id, roles, contract) {
  app.openEdit("person", "");
  app.setField("edit", id, "id");
  app.setField("edit", "Staff " + id, "name");
  if (contract) app.setField("edit", contract, "contract");
  roles.forEach(role => app.setField("hold", role, "roles", true));
  await app.savePerson();
}

async function main() {
  await app.checkEngine();
  ok("the page finds the real engine and reads its rule catalogue",
     nodes.lamp.dataset.state === "ready" && app.state.schema &&
     app.state.schema.rule_types.length > 0, wire());
  if (nodes.lamp.dataset.state !== "ready") {
    throw new Error("nothing is answering on port " + PORT +
      " — start it with: python -m roster.cli serve --port " + PORT);
  }

  ok("the desk starts with no month at all",
     app.state.instance === null && app.state.check === null &&
     fill("period").includes("<h3>Start a month</h3>") &&
     fill("period").includes("<b>Nothing is assumed.</b>"));
  ok("and the other five steps say where a month begins",
     ["staff", "shifts", "rules", "check", "roster"].every(step =>
       fill(step).includes("Start a month on step 1")));
  ok("no example month is asked of the engine",
     asked.every(one => one.indexOf("/sample") < 0) && posts() === 0,
     asked.join(" "));

  app.openEdit("start");
  app.setField("edit", "2026-10-01", "start");
  app.setField("edit", "63", "days");
  ok("a month longer than 62 days is refused before anything is sent",
     app.startTrial() === null);
  app.setField("edit", "31", "days");
  app.setField("hold", "5", "weekend", true);
  app.setField("hold", "6", "weekend", true);
  ok("the first day, the length and the weekly rest are the admin's to choose",
     JSON.stringify(app.startTrial()) ===
       '{"start":"2026-10-01","num_days":31,"holidays":[],"weekend_days":[5,6]}',
     JSON.stringify(app.startTrial()));

  app.startMonth();
  const blank = app.state.instance;
  ok("the month opens empty",
     blank.roles.length === 0 && blank.shifts.length === 0 &&
     blank.employees.length === 0 && blank.demand.length === 0 &&
     blank.rules.length === 0 && blank.horizon.start === "2026-10-01" &&
     blank.horizon.num_days === 31);
  ok("and says what is still to come",
     tick() === "A blank month, Thu 1 October 2026 for 31 days." &&
     tock().includes("Still to come: a role, a shift, somebody on the roll and " +
                     "the demand."));

  for (const role of ROLES) {
    app.openEdit("role", "");
    app.setField("edit", role[0], "id");
    app.setField("edit", role[1], "name");
    await app.saveRole();
  }
  for (const shift of SHIFTS) {
    app.openEdit("shift", "");
    app.setField("edit", shift[0], "id");
    app.setField("edit", shift[1], "name");
    app.setField("edit", shift[2], "start");
    app.setField("edit", shift[3], "hours");
    app.setField("edit-flag", "", "night", shift[4]);
    await app.saveShift();
  }
  ok("the roles and the shifts are held on the desk, not sent to the engine",
     posts() === 0 && app.state.instance.roles.length === 3 &&
     app.state.instance.shifts.length === 3 &&
     app.state.instance.shifts[2].counts_as_night === true, tick());

  await app.runCheck();
  await app.runSolve();
  ok("neither the check nor the search troubles the engine with a half-built month",
     posts() === 0 && app.state.check === null && app.state.solved === null &&
     tick() === "The month is not finished yet.", tick());

  await addPerson(ROLL[0][0], ROLL[0][1], "permanent");
  ok("with a role, a shift and one body the engine is finally asked, and agrees",
     posts() === 1 && app.state.check && app.state.check.ok === true &&
     app.state.instance.employees.length === 1, tick() + " / " + tock());
  for (const person of ROLL.slice(1)) await addPerson(person[0], person[1]);
  ok("the whole roll goes on with the office's own staff numbers",
     app.state.instance.employees.length === 9 &&
     app.state.instance.employees[8].id === "1009" &&
     app.state.instance.employees[0].contract === "permanent", tick());
  app.openEdit("person", "");
  ok("and the next number is read off the roll, not off an example",
     app.state.edit.id === "1010" && app.state.edit.name === "" &&
     app.state.edit.roles.length === 0 &&
     app.state.edit.contract === "permanent",
     JSON.stringify(app.state.edit));

  app.openEdit("demand");
  app.setField("need", "1", "working:M:DSG");
  app.setField("need", "1", "working:E:LSG");
  app.setField("need", "1", "working:N:MTS");
  app.setField("need", "1", "weekend:M:DSG");
  const asking = app.demandTrial();
  ok("the figures are laid across the month, working days and rest days apart",
     asking.each.working === 3 && asking.each.weekend === 1 &&
     asking.total === 75 && asking.demand.length === 75,
     JSON.stringify({ total: asking.total, lines: asking.demand.length }));
  await app.saveDemand();
  ok("the real engine takes the demand and weighs it against the roll",
     app.state.instance.demand.length === 75 &&
     app.state.check.instance.demand_person_shifts === 75 &&
     app.state.check.ok === true, tick() + " / " + tock());
  ok("nothing is left outstanding",
     app.state.ready === undefined && app.ready(app.state.instance) === true &&
     app.stillNeeds(app.state.instance) === "");

  app.startDraft();
  app.setField("type", "max_consecutive_working_days");
  app.setField("param", "5", "max");
  app.setField("severity", "hard");
  await app.saveRule();
  app.startDraft();
  app.setField("type", "min_rest_hours");
  app.setField("param", "11", "hours");
  app.setField("severity", "hard");
  await app.saveRule();
  const rules = app.state.instance.rules;
  ok("the admin's mandatory rules go on the month the page built",
     rules.length === 2 && rules.every(rule => rule.severity === "hard") &&
     Number(rules[0].params.max) === 5 && Number(rules[1].params.hours) === 11,
     JSON.stringify(rules.map(rule => rule.type + "/" + rule.severity)));

  await app.runCheck();
  ok("the engine calls the month built from nothing workable",
     app.state.check.ok === true,
     JSON.stringify((app.state.check || {}).problems || []).slice(0, 240));

  app.setField("seconds", "20", "");
  await app.runSolve();
  const out = app.state.solved;
  ok("and rosters it, every duty covered and no hard rule broken",
     out && out.score.feasible === true && out.score.hard_violations === 0 &&
     out.roster.rows.length === 9 && out.roster.dates.length === 31,
     out ? JSON.stringify(out.score) : "no answer");
  ok("the roster covers the month the page asked for",
     out.roster.dates[0] === "2026-10-01" && out.roster.dates[30] === "2026-10-31");
  ok("nobody works more than the five days in a row the rule allows",
     out.workload.every(person => person.longest_run <= 5),
     JSON.stringify(out.workload.map(person => person.longest_run)));

  app.pickWho("1004");
  const card = fill("shifts");
  const duties = app.dutiesFor("1004");
  ok("one person's own month reads off the real roster",
     card.includes("<h4>1004 · Staff 1004</h4>") && card.includes('class="cal"') &&
     Object.keys(duties).length > 0, Object.keys(duties).length + " duties");
  ok("their calendar counts the same duties the engine reported",
     count(card, /<td class="[^"]*\bon\b/g) === Object.keys(duties).length);
  ok("every duty on the calendar sits inside the month",
     Object.keys(duties).every(iso => iso >= "2026-10-01" && iso <= "2026-10-31"));

  app.openEdit("period");
  app.setField("edit", "2026-11-02", "start");
  const moved = app.periodTrial();
  const perDay = {};
  (moved ? moved.demand.demand : []).forEach(line => {
    perDay[line.day] = (perDay[line.day] || 0) + 1;
  });
  const days = Object.keys(perDay);
  ok("moving the month relays the demand on the new weekdays",
     moved && moved.delta === 32 && moved.demand.laid === true &&
     days.length === 31 && days.every(day => day >= 0 && day <= 30) &&
     days.filter(day => perDay[day] === 1).length === 8 &&
     days.filter(day => perDay[day] === 3).length === 23,
     moved && JSON.stringify({ d: moved.delta, l: moved.demand.demand.length }));
  await app.savePeriod();
  ok("the real engine accepts the moved month",
     app.state.instance.horizon.start === "2026-11-02" &&
     app.state.instance.demand.length === 77 &&
     app.state.instance.rules.length === 2 && app.state.check.ok === true, tick());
  ok("and the roster built for the old dates is cleared",
     app.state.solved === null &&
     fill("roster").includes("Generate the roster"));

  app.state.instance.shifts[0].duration_min = 0;
  await app.runCheck();
  ok("a month the engine cannot read is refused in the engine's own words",
     tock().includes("duration_min must be in 1..1440"), tick() + " / " + tock());
  app.state.instance.shifts[0].duration_min = 480;

  await app.removeRole("DSG");
  ok("a role the demand and the roll still hold cannot be removed",
     app.state.instance.roles.length === 3 &&
     tick() === "The DSG role is still in use." &&
     tock().includes("9 on the roll hold it"), tick() + " / " + tock());
  await app.removeShift("N");
  ok("nor a shift the demand still asks for",
     app.state.instance.shifts.length === 3 &&
     tick() === "The N shift is still in use.", tick());

  app.openEdit("start");
  app.setField("edit", "2027-01-04", "start");
  app.setField("edit", "28", "days");
  const settled = posts();
  app.startMonth();
  const over = app.state.instance;
  ok("starting a different month empties the desk without asking the engine",
     posts() === settled && over.horizon.start === "2027-01-04" &&
     over.horizon.num_days === 28 && over.employees.length === 0 &&
     over.roles.length === 0 && over.shifts.length === 0 &&
     over.demand.length === 0 && over.rules.length === 0);
  ok("and takes the roster, the verdict and the roll with it",
     app.state.solved === null && app.state.check === null &&
     app.state.dirty === false &&
     fill("check").includes("cannot judge this one until"));
  ok("no example data was ever fetched, start to finish",
     asked.every(one => one.indexOf("/sample") < 0), asked.join(" "));

  console.log("\ncalls made: " + asked.join(", "));
  console.log(failures ? "\n" + failures + " live check(s) failed"
                       : "\nall live checks pass");
  process.exit(failures ? 1 : 0);
}
main().catch(err => {
  console.log("\n" + err.message);
  process.exit(1);
});
