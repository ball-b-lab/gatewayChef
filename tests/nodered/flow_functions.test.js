const fs = require("fs");
const flows = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const fn = name => flows.find(n => n.type === "function" && n.name === name).func;
const ctx = {}, glob = { flowVersion: "1.1.0" };
const flow = { get: k => ctx[k], set: (k, v) => { ctx[k] = v; } };
const global = { get: k => glob[k], set: (k, v) => { glob[k] = v; } };
const node = { status() {}, warn: m => console.log("WARN", m), error: m => console.log("ERR", m) };
const run = (name, msg) => new Function("msg", "flow", "global", "node", "RED", "Buffer", fn(name))(
  msg, flow, global, node, { util: { cloneMessage: m => JSON.parse(JSON.stringify(m)) } }, Buffer);
const eui = Buffer.from("24E124FFFEF783E6", "hex");
const push = obj => Buffer.concat([Buffer.from([2, 0xab, 0xcd, 0x00]), eui, Buffer.from(JSON.stringify(obj))]);
const ok = (c, t) => { console.log((c ? "OK   " : "FAIL ") + t); if (!c) process.exitCode = 1; };

// PUSH_DATA with stat
let out = run("Semtech UDP: ACK + JSON", { payload: push({ stat: { time: "x", rxnb: 0 } }), ip: "127.0.0.1", port: 40000 });
ok(out[0].payload.equals(Buffer.from([2, 0xab, 0xcd, 0x01])) && out[0].ip === "127.0.0.1" && out[0].port === 40000, "PUSH_ACK mit Token an Absender");
ok(JSON.parse(out[1].payload).stat, "stat als JSON-Text weitergegeben");
ok(ctx.lastStatReceived > 0, "lastStatReceived gesetzt (repariert /lora/health)");
// PUSH_DATA with rxpk
const rx = { rxpk: [{ tmst: 1, freq: 868.1, datr: "SF7BW125", rssi: -57, lsnr: 9.5, data: "QAEAAAAAAQAB" }] };
out = run("Semtech UDP: ACK + JSON", { payload: push(rx), ip: "127.0.0.1", port: 40000 });
ok(out[1].payload === JSON.stringify(rx), "rxpk unveraendert als Text");
// PULL_DATA
out = run("Semtech UDP: ACK + JSON", { payload: Buffer.concat([Buffer.from([2, 1, 2, 0x02]), eui]), ip: "127.0.0.1", port: 40001 });
ok(out[0].payload.equals(Buffer.from([2, 1, 2, 0x04])) && out[1] === null, "PULL_DATA -> PULL_ACK, keine Daten");
// garbage
ok(run("Semtech UDP: ACK + JSON", { payload: Buffer.from([1, 2]) }) === null, "kaputtes Paket verworfen");
out = run("Semtech UDP: ACK + JSON", { payload: Buffer.concat([Buffer.from([2, 9, 9, 0]), eui, Buffer.from("{kaputt")]) });
ok(out[0].payload[3] === 1 && out[1] === null, "ungueltiges JSON: trotzdem ACK, keine Daten");

// Buffer -> /status like the app sees it
glob.statusLog = []; glob.nextSeq = 1; glob.bootId = 123;
run("Buffer messages", { payload: JSON.stringify(rx) });
const st = run("Return Status Since", { req: { query: { since: "0" } } });
const item = st.payload.items[0];
const appJson = (t => t.substring(t.indexOf("{"), t.lastIndexOf("}") + 1))(item.payload);   // = GatewayMessageParser.extractJsonPayload
ok(JSON.parse(appJson).rxpk[0].rssi === -57 && st.payload.boot_id === 123 && st.payload.latest_seq === 1, "/status liefert rxpk im App-Format");

// health
const h = run("Drive-by Health", {});
ok(h.statusCode === 200 && h.payload.counts.rxpk === 1 && h.payload.counts.stat === 1 && h.payload.gateway_eui === "24E124FFFEF783E6" && h.payload.flow_version === "1.1.0", "/driveby/health: " + JSON.stringify(h.payload.counts));
// lora/health with fresh stat but no ACK -> network status from log path unchanged
ctx.gatewayStatus = { status: "ONLINE", seconds_since_ack: 3, last_seen: "x" };
const lh = run("read GW status and send ONLINE or Offline", {});
ok(lh.statusCode === 200 && lh.payload.lns_connected, "/lora/health ONLINE mit stat aus UDP");
// graph template now renders the active button
const g = run("supply graph", { payload: { hours: "1" } });
ok(!g.payload.includes("${hours") && g.payload.includes("btn active"), "Graph: aktiver Button wird markiert");
