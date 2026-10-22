/* Audit every quote the site can give against prices.js (built from the buyer sheets).

Usage: node tools/audit.js [index.html] [prices.js]
Exits 1 and prints each problem when a check fails, 0 when everything is clean.

Checks:
  margin       every standard quote leaves $50-$100 (plus $5 rounding) under the buyer price; blacklisted at least $75
  over-buyer   no quote of any kind pays more than the buyer pays us
  progression  the number shown never goes up as the seller answers (series -> model -> storage -> ... -> blacklist)
  labels       each model's "Up to" label equals the best quote that model can reach
  sheet        no worse answer pays more than a better one in prices.js (grade, lock, storage)
*/
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..");
const html = fs.readFileSync(process.argv[2] || path.join(root, "index.html"), "utf8");
global.window = {}; eval(fs.readFileSync(process.argv[3] || path.join(root, "prices.js"), "utf8"));
const PRICES = window.PRICES;
// Hen's rules, written here on purpose (not read from the page) so a bad edit to the page gets caught
const RULE = { min: 50, max: 100, blacklistMin: 75 };

// Pull the pricing code straight out of the page so the audit always tests what is live
const pick = (a, b) => { const i = html.indexOf(a), j = html.indexOf(b, i); if (i < 0 || j < 0) throw new Error("audit: can't find " + a); return html.slice(i, j); };
const code = [
  pick("function familyOf", "function families"),
  pick("const MARGIN", "const TEXT_TO"),
  pick("const GRADES =", "function estimate()"),
].join("\n").replace(/^const /gm, "var ").replace(/^function familyOf/m, "var familyOf = function");
const sandbox = new Function("PRICES", "window", code + "\nreturn { quote, bestQuote, familyOf, worse, MARGIN, LOCKED_FALLBACK, FINANCED_FACTOR, BLACKLIST_DED, ICLOUD_FLAT };");
const { quote, bestQuote, familyOf, worse, MARGIN, LOCKED_FALLBACK, FINANCED_FACTOR, BLACKLIST_DED } = sandbox(PRICES, window);

const problems = {}; const add = (k, s) => (problems[k] = problems[k] || []).push(s);
const GRADES = ["S", "O", "A", "B", "BC", "C", "D", "DOA"];
const est = (k, m, s) => { // the page's estimate(): unanswered storage/lock take the best option
  const d = PRICES[k][m], sts = s.storage != null ? [s.storage] : d.st.map((_, i) => i), ls = s.lock != null ? [s.lock] : [0, 1];
  let b = 0; for (const storage of sts) for (const lock of ls) b = Math.max(b, quote(k, m, { ...s, storage, lock }) || 0); return b || null;
};
let quotes = 0;

for (const k of ["iphone", "samsung", "ipad"]) {
  const fam = {};
  for (const m in PRICES[k]) fam[familyOf(k, m)] = Math.max(fam[familyOf(k, m)] || 0, bestQuote(k, m));
  for (const m in PRICES[k]) {
    const d = PRICES[k][m];
    // sheet consistency
    d.st.forEach((st, si) => {
      for (const L of ["U", "L"]) {
        const g = d.P[st][L]; if (!g) continue; let prev = null, pg = null;
        for (const x of GRADES) { if (g[x] == null) continue; if (prev != null && g[x] > prev) add("sheet", `${m} ${st} ${L}: ${x} $${g[x]} > ${pg} $${prev}`); prev = g[x]; pg = x; }
        if (L === "L" && d.P[st].U) for (const x of GRADES) if (g[x] != null && d.P[st].U[x] != null && g[x] > d.P[st].U[x]) add("sheet", `${m} ${st} ${x}: locked $${g[x]} > unlocked $${d.P[st].U[x]}`);
        if (si > 0) { const P = d.P[d.st[si - 1]][L]; if (P) for (const x of GRADES) if (P[x] != null && g[x] != null && g[x] < P[x]) add("sheet", `${m} ${st} ${L} ${x}: $${g[x]} < smaller storage $${P[x]}`); }
      }
    });
    // labels
    const best = bestQuote(k, m), shown = est(k, m, {});
    if ((best || 0) !== (shown || 0)) add("labels", `${m}: label $${best}, first number shown $${shown}`);
    // every answer path
    for (let st = 0; st < d.st.length; st++) for (const usage of [0, 1, 2]) for (const cond of usage === 2 ? [0, 1, 2] : [undefined])
      for (const damage of usage === 2 ? [0, 1, 2, 3, 4, 5] : [undefined]) for (const lock of [0, 1, 2, 3]) for (const black of [0, 1, 2]) {
        const a = { storage: st, usage, cond, damage, lock, black }, v = quote(k, m, a); quotes++;
        // the buyer price for exactly these answers
        const row = d.P[d.st[st]], lk = lock === 0 ? "U" : "L";
        let g = row[lk] || (lk === "L" && row.U ? Object.fromEntries(Object.entries(row.U).map(([x, p]) => [x, p * LOCKED_FALLBACK])) : null);
        if (black === 2) g = PRICES.iphone_db?.[m]?.[d.st[st]];
        let grade = usage === 0 ? "S" : usage === 1 ? "O" : ["A", "B", "BC"][cond], ded = black === 2 ? BLACKLIST_DED : 0;
        if (damage === 1 || damage === 3) grade = worse(grade, "C");
        if (damage === 2 || damage === 3) { if (d.back) ded += d.back; else grade = worse(grade, "C"); }
        if (damage === 4) grade = worse(grade, "D");
        if (damage === 5) grade = "DOA";
        let buyer = g?.[grade];
        if (buyer == null && grade === "S") buyer = g?.O ?? g?.A;
        if (buyer == null && grade === "O") buyer = g?.A;
        if (buyer == null && grade === "BC" && g) buyer = g.B != null && g.C != null ? (g.B + g.C) / 2 : g.C;
        if (lock === 3) { // iCloud: flat offer against Device Buyers' iCloud/parts price
          const ic = PRICES.icloud?.[m];
          if (v != null && (!ic || v > ic.AB - 20)) add("over-buyer", `${m} ${d.st[st]} iCloud: offer $${v} vs buyer $${ic?.AB}`);
          continue;
        }
        if (v == null) continue;
        if (buyer == null) { add("over-buyer", `${m} ${d.st[st]} ${JSON.stringify(a)}: offer $${v} but no buyer price`); continue; }
        if (lock === 2) buyer *= FINANCED_FACTOR;
        const margin = buyer - ded - v;
        const floor = black === 2 ? RULE.blacklistMin : RULE.min;
        if (margin < floor) add(margin < 0 ? "over-buyer" : "margin", `${m} ${d.st[st]} ${JSON.stringify(a)}: buyer $${Math.round(buyer - ded)}, offer $${v}, margin $${Math.round(margin)}`);
        else if (black !== 2 && margin > RULE.max + 5) add("margin", `${m} ${d.st[st]} ${JSON.stringify(a)}: buyer $${Math.round(buyer - ded)}, offer $${v}, margin $${Math.round(margin)} (over $${RULE.max})`);
      }
    // progression, as the seller answers in order
    for (let st = 0; st < d.st.length; st++) for (const u of [0, 1, 2]) for (const c of u === 2 ? [0, 1, 2] : [null]) for (const dm of u === 2 ? [0, 1, 2, 3, 4, 5] : [null]) for (const l of [0, 1, 2, 3]) for (const bl of [0, 1, 2]) {
      const s = {}, seq = [["series", fam[familyOf(k, m)]], ["model", best], ["picked", est(k, m, s)]];
      if (d.st.length > 1) { s.storage = st; seq.push(["storage", est(k, m, s)]); } else s.storage = 0;
      s.usage = u; seq.push(["new/used", est(k, m, s)]);
      if (c != null) { s.cond = c; seq.push(["wear", est(k, m, s)]); s.damage = dm; seq.push(["damage", est(k, m, s)]); }
      s.lock = l; seq.push(["lock", est(k, m, s)]); s.black = bl; seq.push(["blacklist", est(k, m, s)]);
      let prev = Infinity, pn = "";
      for (const [n, v] of seq) { if (v != null && v > prev) { add("progression", `${m} ${JSON.stringify(s)}: ${n} $${v} > ${pn} $${prev}`); break; } if (v != null) { prev = v; pn = n; } }
    }
  }
}

const names = Object.keys(problems);
console.log(`Audited ${quotes.toLocaleString()} quotes across ${Object.values(PRICES).filter(x => typeof x === "object").length} price tables (prices updated ${PRICES.updated}).`);
if (!names.length) { console.log("All checks passed: margin, over-buyer, progression, labels, sheet."); process.exit(0); }
for (const n of names) { console.log(`\n${n}: ${problems[n].length} problem(s)`); console.log(problems[n].slice(0, 15).map(x => "  " + x).join("\n")); }
process.exit(1);
