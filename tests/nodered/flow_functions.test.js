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

// app poll tracking: /status call is recorded and reported in /driveby/health
run("Return Status Since", { req: { query: {}, ip: "172.30.100.7", headers: { "user-agent": "dbmonitor/2.1" } } });
const h2 = run("Drive-by Health", {});
ok(h2.payload.app.client === "172.30.100.7" && h2.payload.app.polls === 2 && h2.payload.app.seconds_since_poll === 0
   && h2.payload.app.agent === "dbmonitor/2.1", "App-Abruf erfasst: " + JSON.stringify(h2.payload.app));

// device-info race fix exists from 1.3.1 on (bundle version from the "gatewaychef-flow x.y.z" comment node)
const bundleVersion = ((flows.find(n => /^gatewaychef-flow /.test(n.name || "")) || {}).name || "0.0.0").split(" ")[1].split(".").map(Number);
if (bundleVersion[0] * 1e6 + bundleVersion[1] * 1e3 + bundleVersion[2] >= 1003001) {
// device-info: two requests at once must both get their MAC (flow <= 1.3.0 cleared a shared flow.temp_mac -> 00:00…)
const ifc = "wg0       Link encap:UNSPEC\n          inet addr:172.30.0.117  P-t-P:172.30.0.117\n          UP POINTOPOINT RUNNING\n";
const iw = "phy#0\n\tInterface wlan0\n\t\tssid Gateway_F783E6\n";
const reqA = run("safe store ssid", Object.assign(run("safe store mac", { payload: "24:e1:24:f7:83:e6\n" }), { payload: iw }));
const reqB = run("safe store ssid", Object.assign(run("safe store mac", { payload: "24:e1:24:f7:83:e6\n" }), { payload: iw }));
const ansA = run("function 2", Object.assign(reqA, { payload: ifc })).payload.device;
const ansB = run("function 2", Object.assign(reqB, { payload: ifc })).payload.device;
ok(ansA.mac === "24:E1:24:F7:83:E6" && ansB.mac === "24:E1:24:F7:83:E6" && ansB.eui === "24E124FFFEF783E6"
   && ansB.ssid === "Gateway_F783E6" && ansB.vpn_ip === "172.30.0.117", "device-info parallel: beide Antworten mit MAC/EUI " + ansB.eui);
const later = run("function 2", { payload: ifc }).payload.device;   // msg without gw_mac (e.g. other entry) -> last known MAC
ok(later.mac === "24:E1:24:F7:83:E6", "device-info ohne msg.gw_mac: letzte bekannte MAC statt 00:00");
}
