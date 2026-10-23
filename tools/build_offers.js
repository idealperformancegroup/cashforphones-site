/* Build the offer sheet the GoHighLevel chat bot reads: offers/index.html and offers.txt.

Usage: node tools/build_offers.js [index.html] [prices.js]
Run it after every price refresh (the 12-hour price audit does), so the sheet always matches the site.

Every number comes from the page's own quote(), so the bot can never offer more than the site.
Each condition shows three numbers, open -> counter -> max:
  open     what the bot offers first
  counter  its one step up when the seller pushes back
  max      the site's offer, the most the bot can ever say (keeps our $50+ margin)
Buyer sheet prices are left out on purpose, so the bot can't leak them.
*/
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..");
const html = fs.readFileSync(process.argv[2] || path.join(root, "index.html"), "utf8");
global.window = {}; eval(fs.readFileSync(process.argv[3] || path.join(root, "prices.js"), "utf8"));
const PRICES = window.PRICES;

// Same extraction as tools/audit.js: price with the page's live code
const pick = (a, b) => { const i = html.indexOf(a), j = html.indexOf(b, i); if (i < 0 || j < 0) throw new Error("offers: can't find " + a); return html.slice(i, j); };
const code = [pick("const MARGIN", "const TEXT_TO"), pick("const GRADES =", "function estimate()")].join("\n").replace(/^const /gm, "var ");
const { quote } = new Function("PRICES", "window", code + "\nreturn { quote };")(PRICES, window);

// Haggle room under the max: about 10% of the offer, at least $10, at most $60
const ladder = max => {
  if (max == null) return "text offer";
  if (max < 30) return `${max} (no haggle)`;
  const gap = Math.min(60, Math.max(10, Math.floor(max * 0.1 / 5) * 5)), counter = max - Math.floor(gap / 2 / 5) * 5;
  return `${max - gap} > ${counter} > ${max}`;
};
const CONDS = [ // label, answers in the site's quote flow
  ["Sealed", { usage: 0 }], ["Open box", { usage: 1 }],
  ["Like new", { usage: 2, cond: 0, damage: 0 }], ["Good", { usage: 2, cond: 1, damage: 0 }], ["Fair", { usage: 2, cond: 2, damage: 0 }],
  ["Cracked screen", { usage: 2, cond: 1, damage: 1 }], ["Cracked back", { usage: 2, cond: 1, damage: 2 }], ["Screen and back cracked", { usage: 2, cond: 1, damage: 3 }],
  ["Something doesn't work", { usage: 2, cond: 1, damage: 4 }]
]; // won't turn on is left out: dead phones go to Hen
const LOCKS = [["Unlocked", 0], ["Carrier locked", 1], ["Financed", 2]];
const BRANDS = [["iphone", "iPhones"], ["samsung", "Samsung Galaxy"], ["ipad", "iPads"]];

const now = new Date(), stamp = now.toLocaleString("en-US", { timeZone: "America/Chicago", dateStyle: "medium", timeStyle: "short" }) + " CT";
const sections = [];
for (const [brand, title] of BRANDS) {
  const lines = [];
  for (const model in PRICES[brand]) {
    const d = PRICES[brand][model];
    d.st.forEach((st, si) => {
      const name = st === "*" ? `${model} (any storage)` : `${model} ${st}`;
      for (const [lockName, lock] of LOCKS) {
        const parts = CONDS.map(([c, a]) => `${c} ${ladder(quote(brand, model, { storage: si, lock, black: 0, ...a }))}`);
        lines.push(`${name} | ${lockName} | ${parts.join("; ")}; Won't turn on: hand off to Hen`);
      }
      if (brand === "iphone") {
        const ic = quote(brand, model, { storage: si, usage: 2, cond: 0, damage: 0, lock: 3, black: 0 });
        lines.push(`${name} | iCloud locked | ${ic ? `$${ic} flat, no haggle, only if no cracks or damage and not blacklisted` : "no set price, hand off to Hen"}`);
      }
    });
  }
  sections.push([title, lines]);
}

const rules = [
  `Cash for Phones Louisiana offer sheet. Updated ${stamp} (prices dated ${PRICES.updated}).`,
  "Each line is one phone: model and storage | lock status | condition, then three dollar amounts: OPEN > COUNTER > MAX.",
  "OPEN is the first offer. COUNTER is the one step up if the seller pushes back. MAX is the most we ever pay for that phone in that condition. Never go above MAX.",
  "All offers are \"up to\" amounts, confirmed after a quick in-person check. Payment is cash, Cash App or Zelle.",
  "\"text offer\" means there is no set price: hand off to Hen. Phones that won't turn on, blacklisted, MDM-locked, prepaid-carrier (Straight Talk, Tracfone, Total, Xfinity) and other brands: hand off to Hen.",
  "Conditions: Like new = no visible scratches. Good = light scratches. Fair = heavy scratches, dents or weak battery. Something doesn't work = Face ID, camera, speaker, buttons or charging. Financed = still paying it off."
];
const txt = [...rules, "", ...sections.flatMap(([t, l]) => [`== ${t} ==`, ...l, ""])].join("\n");
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const page = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Offer sheet | Cash for Phones Louisiana</title>
<style>body{font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px;color:#1d1530;background:#fff}h1{font-size:22px}h2{font-size:18px;margin-top:28px}p{margin:4px 0}li{margin:3px 0}</style>
</head><body>
<h1>Cash for Phones Louisiana offer sheet</h1>
${rules.map(r => `<p>${esc(r)}</p>`).join("\n")}
${sections.map(([t, l]) => `<h2>${esc(t)}</h2>\n<ul>\n${l.map(x => `<li>${esc(x)}</li>`).join("\n")}\n</ul>`).join("\n")}
</body></html>
`;
fs.mkdirSync(path.join(root, "offers"), { recursive: true });
fs.writeFileSync(path.join(root, "offers", "index.html"), page);
fs.writeFileSync(path.join(root, "offers.txt"), txt);
console.log(`offers: ${sections.reduce((n, [, l]) => n + l.length, 0)} lines, ${Math.round(txt.length / 1024)} KB (prices ${PRICES.updated})`);
