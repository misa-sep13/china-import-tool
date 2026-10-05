// 楽天RMSの広告（RPP）の実績を、輸入管理ツールへ取り込む。
//
// 画面を触らずに、画面が使っているのと同じAPIをそのまま呼ぶ。
//   ・毎日の消化 … POST /rpp/api/reports/search（集計単位=すべての広告、日ごと）
//   ・商品ごと   … POST /rpp/api/reports/downloadAsync で全商品レポートを作らせ、
//                  GET /rpp/api/download/list で出来上がりを待ち、
//                  GET /rpp/api/download/report でZIPを受け取る
//
// 商品ごとを検索APIで直に取れないのは、絞り込みが「実績額TOP10」までしか
// 選べないため。全商品の数字は全商品レポート（CSV）にしか入っていない。
//
// 画面の選択（集計単位・集計期間）は一切書き換えない。送る中身を変えるだけ。
(function () {
  const DEFAULT_BACKEND = "https://china-import-tool.onrender.com";
  const ORIGIN = location.origin;
  const REPORT_TYPE_ALL_ITEM = 13;   // 全商品レポート
  const STATUS_DONE = 2;             // 完了
  const GAP_MS = 6 * 60 * 60 * 1000; // 同じ種類は6時間に1回まで

  let panel = null;
  let status = "";
  let busy = false;
  const notes = [];

  const setStatus = (t) => { status = t; render(); };
  const note = (t) => { notes.push(String(t).slice(0, 300)); };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const ymd = (d) => `${d.getFullYear()}-` +
    `${String(d.getMonth() + 1).padStart(2, "0")}-` +
    `${String(d.getDate()).padStart(2, "0")}`;

  // ---- 楽天のAPIを呼ぶ ----

  // 画面はこの合言葉をヘッダに付けている。付けないと403で弾かれる
  const xsrf = () => {
    const m = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  };

  const headers = () => ({
    "Content-Type": "application/json",
    Accept: "application/json, text/plain, */*",
    "X-XSRF-TOKEN": xsrf(),
  });

  // 画面が送っているのと同じ形。表示／出力項目は全部入りにしてある
  const condition = (patch) => Object.assign({
    page: 1, selectionType: 1, periodType: 0,
    startDate: "", endDate: "",
    reportFilter: 1, campaignType: "1", rankType: 1,
    allUsers: true, newUsers: true, existingUsers: true,
    noOfClicks: true, adsalesBefore: true, cpc: true,
    h12: true, h720: true,
    gms: true, roas: true, cv: true, cvr: true, cpa: true,
  }, patch);

  async function post(path, body) {
    const res = await fetch(ORIGIN + path, {
      method: "POST", credentials: "include",
      headers: headers(), body: JSON.stringify(body),
    });
    const json = await res.json().catch(() => null);
    if (!res.ok || (json && json.errors && json.errors.length)) {
      const msg = json && json.errors && json.errors[0]
        ? String(json.errors[0].message || "").split(String.fromCharCode(10))[0]
        : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return json;
  }

  async function get(path) {
    const res = await fetch(ORIGIN + path,
      { credentials: "include", headers: headers() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res;
  }

  // ---- 毎日の消化 ----

  async function fetchDaily(from, to) {
    const json = await post("/rpp/api/reports/search",
      condition({ selectionType: 1, periodType: 2,
                  startDate: from, endDate: to }));
    return ((json || {}).data || {}).rppReports || [];
  }

  // ---- 商品ごと（全商品レポート） ----

  async function historyList() {
    const res = await get("/rpp/api/download/list");
    const data = (await res.json()).data || {};
    return [].concat(data.userHistoryList || [], data.batchHistoryList || []);
  }

  const isAllItem = (r) => Number(r.reportType) === REPORT_TYPE_ALL_ITEM;

  async function makeAllItemReport(from, to) {
    const before = new Set((await historyList()).map((r) => r.id));
    await post("/rpp/api/reports/downloadAsync",
      condition({ selectionType: 3, periodType: 0,
                  startDate: from, endDate: to }));

    // 作られるまで待つ。たいてい十数秒で出来る
    for (let i = 0; i < 40; i++) {
      await sleep(5000);
      const list = await historyList();
      const fresh = list.find((r) => !before.has(r.id) && isAllItem(r)
                                     && Number(r.status) === STATUS_DONE);
      if (fresh) return fresh;
      setStatus(`全商品レポートが出来るのを待っています…（${(i + 1) * 5}秒）`);
    }
    throw new Error("全商品レポートが出来上がりませんでした");
  }

  async function downloadReport(item) {
    const res = await get(
      `/rpp/api/download/report?downloadId=${item.id}` +
      `&reportType=${item.reportType}`);
    const bytes = new Uint8Array(await res.arrayBuffer());
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return { name: `rpp_item_report_${item.id}.zip`, b64: btoa(s) };
  }

  // ---- 除外商品（広告を止めている商品） ----
  //
  // 在庫切れで止めたまま、入荷しても止まりっぱなしになりやすい。
  // 一覧をそのままツールへ送って、在庫が戻ったら知らせてもらう。

  // ツールで「再開する」を押したものを、RMSの除外から外す。
  // 広告費が動く操作なので、押されたものだけを、押された数だけ外す
  async function runResumeQueue() {
    const q = await ask("/api/rakuten/ads/resume-queue");
    const items = (q && q.items) || [];
    if (!items.length) return 0;
    setStatus(`広告を再開しています（${items.length}件）…`);
    try {
      const res = await fetch(ORIGIN + "/rpp/api/exclude/remove", {
        method: "POST", credentials: "include",
        headers: headers(), body: JSON.stringify(items),
      });
      const json = await res.json().catch(() => null);
      const d = (json && json.data) || {};
      if (!res.ok || (json && json.errors && json.errors.length)) {
        throw new Error((json && json.errors && json.errors[0].message)
                        || `HTTP ${res.status}`);
      }
      await toTool("rows", { payload: { done: items },
                             path: "/api/rakuten/ads/resume-done" });
      return Number(d.successCount || items.length);
    } catch (e) {
      await toTool("rows", {
        payload: { failed: items, error: String(e.message || e) },
        path: "/api/rakuten/ads/resume-done" });
      throw e;
    }
  }

  // ツールで「広告を止める」を押したものを、RMSの除外へ入れる
  async function runExcludeQueue() {
    const q = await ask("/api/rakuten/ads/exclude-queue");
    const items = (q && q.items) || [];
    if (!items.length) return 0;
    setStatus(`広告を止めています（${items.length}件）…`);
    try {
      const res = await fetch(ORIGIN + "/rpp/api/exclude/add", {
        method: "POST", credentials: "include",
        headers: headers(), body: JSON.stringify(items),
      });
      const json = await res.json().catch(() => null);
      if (!res.ok || (json && json.errors && json.errors.length)) {
        throw new Error((json && json.errors && json.errors[0].message)
                        || `HTTP ${res.status}`);
      }
      await toTool("rows", { payload: { done: items },
                             path: "/api/rakuten/ads/exclude-done" });
      return Number(((json || {}).data || {}).successCount || items.length);
    } catch (e) {
      await toTool("rows", {
        payload: { failed: items, error: String(e.message || e) },
        path: "/api/rakuten/ads/exclude-done" });
      throw e;
    }
  }

  async function fetchExcluded() {
    const items = [];
    for (let page = 1; page <= 20; page++) {
      const res = await get(`/rpp/api/exclude?page=${page}&sortBy=-updatedAt`);
      const data = (await res.json()).data || {};
      const got = data.items || [];
      items.push(...got);
      const total = Number(data.totalCount || 0);
      if (!got.length || items.length >= total) break;
      await sleep(400);
    }
    return items;
  }

  // ---- ツールへ送る ----

  // ツールに聞く（どの日が足りないか、再開待ちは何か）
  async function ask(path) {
    const cfg = await chrome.storage.local.get(["backend", "token"]);
    const res = await chrome.runtime.sendMessage({
      type: "ask", backend: cfg.backend || DEFAULT_BACKEND,
      token: cfg.token, path,
    });
    return res && res.ok ? res.data : null;
  }

  async function missingDays() {
    const d = await ask("/api/rakuten/ads/item-days?days=10");
    return (d && d.missing) || [];
  }

  async function toTool(type, payload) {
    const cfg = await chrome.storage.local.get(["backend", "token"]);
    if (!cfg.token) throw new Error("トークンが未設定です");
    const res = await chrome.runtime.sendMessage(Object.assign({
      type, backend: cfg.backend || DEFAULT_BACKEND, token: cfg.token,
    }, payload));
    if (!res || !res.ok) throw new Error((res && res.error) || "理由不明");
    return res.data || {};
  }

  // ---- ひととおり ----

  async function run(force) {
    if (busy) return;
    const cfg = await chrome.storage.local.get(["token", "auto", "auto_last"]);
    if (!cfg.token) {
      if (force) setStatus("先に「設定」でトークンを入れてください");
      return;
    }
    if (!force && cfg.auto === false) return;

    // 押された「止める」「再開する」は、取り込みの間隔と関係なく毎回やる。
    // 取り込みを6時間に1回に絞っているので、ここを後ろに置くと
    // 押したのにいつまでも実行されないことになる
    busy = true;
    render();
    try {
      const resumed = await runResumeQueue();
      if (resumed) setStatus(`広告を再開しました（${resumed}件）`);
      const stopped = await runExcludeQueue();
      if (stopped) setStatus(`広告を止めました（${stopped}件）`);

      // 広告を止めている商品の一覧。これが無いと「もう止めている商品」に
      // 「止めろ」と言い続けることになるので、取り込みの間隔とは別に毎回送る
      setStatus("除外商品を確かめています…");
      const ex = await toTool("rows", {
        payload: { items: await fetchExcluded() },
        path: "/api/rakuten/ads/excluded" });
      setStatus(`除外商品 ${ex.saved}件を確かめました`);
    } catch (e) {
      note(e.message || e);
      setStatus(`できませんでした：${e.message || e}`);
      busy = false;
      render();
      return;
    }
    busy = false;

    const last = cfg.auto_last || {};
    const now = Date.now();
    const want = ["daily", "product"].filter(
      (k) => force || now - (last[k] || 0) >= GAP_MS);
    if (!want.length) { render(); return; }

    // 集計は昨日まで。毎日の消化は3か月以内、商品ごとは今月ぶん
    const to = new Date(); to.setDate(to.getDate() - 1);
    const dailyFrom = new Date(to); dailyFrom.setDate(dailyFrom.getDate() - 87);
    const monthFrom = new Date(to.getFullYear(), to.getMonth(), 1);
    const done = Object.assign({}, last);

    busy = true;
    render();
    try {
      if (want.includes("daily")) {
        setStatus("毎日の消化をもらっています…");
        const rows = await fetchDaily(ymd(dailyFrom), ymd(to));
        const r = await toTool("rows", { payload: { kind: "daily", rows } });
        done.daily = Date.now();
        setStatus(`取り込みました：毎日の消化 ${r.saved}行`);
      }
      if (want.includes("product")) {
        setStatus("全商品レポートを申し込んでいます…");
        const item = await makeAllItemReport(ymd(monthFrom), ymd(to));
        setStatus("全商品レポートを受け取っています…");
        const file = await downloadReport(item);
        const r = await toTool("upload", file);
        done.product = Date.now();
        setStatus(`取り込みました：商品ごと ${r.saved}行`);
      }
      // 商品ごと・日ごと。クリックの暴走は商品単位で起きるので、
      // 1日だけのレポートを作って溜めていく。1回に3日ぶんまで
      const missing = (await missingDays()).slice(0, 3);
      for (let i = 0; i < missing.length; i++) {
        const day = missing[i];
        setStatus(`${day} の商品別を作っています…（${i + 1}/${missing.length}）`);
        const item = await makeAllItemReport(day, day);
        const file = await downloadReport(item);
        const r = await toTool("upload", file);
        setStatus(`取り込みました：${day} の商品別 ${r.saved}行`);
      }
      await chrome.storage.local.set({ auto_last: done });
    } catch (e) {
      note(e.message || e);
      setStatus(`取り込めませんでした：${e.message || e}`);
    } finally {
      busy = false;
      render();
    }
  }

  // ---- 画面の隅に出す小さな操作盤 ----

  async function configure() {
    const cfg = await chrome.storage.local.get(["backend", "token"]);
    const backend = prompt("輸入管理ツールのURL", cfg.backend || DEFAULT_BACKEND);
    if (backend === null) return;
    const token = prompt("サービストークン（AUTH_SERVICE_TOKEN）", cfg.token || "");
    if (token === null) return;
    await chrome.storage.local.set({
      backend: backend.trim().replace(/\/+$/, ""), token: token.trim() });
    setStatus("保存しました");
  }

  async function toggleAuto() {
    const cfg = await chrome.storage.local.get(["auto"]);
    const next = cfg.auto === false;
    await chrome.storage.local.set({ auto: next });
    setStatus(next ? "広告の画面を開いたら自動で取り込みます"
                   : "自動取り込みを止めました");
  }

  function copyNotes() {
    const text = [location.href, `いまの表示: ${status}`,
      `合言葉: ${xsrf() ? "あり" : "なし"}`]
      .concat(notes.slice(-20)).join(String.fromCharCode(10));
    navigator.clipboard.writeText(text).then(
      () => setStatus("状況をコピーしました"), () => alert(text));
  }

  function mk(label, bg, fn) {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText = "padding:5px 10px;border:none;border-radius:5px;" +
      `cursor:pointer;font-size:12px;background:${bg};color:#fff`;
    b.onclick = fn;
    return b;
  }

  async function render() {
    if (!document.body) return;
    const cfg = await chrome.storage.local.get(["token", "auto"]);
    if (!panel) {
      panel = document.createElement("div");
      panel.style.cssText =
        "position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#fff;" +
        "border:1px solid #cbd5e1;border-radius:8px;padding:10px 12px;font-size:13px;" +
        "box-shadow:0 4px 16px rgba(0,0,0,.18);font-family:sans-serif;" +
        "max-width:320px;line-height:1.6";
      document.body.appendChild(panel);
    }
    panel.innerHTML = "";

    const title = document.createElement("div");
    title.style.cssText = "font-weight:700;margin-bottom:4px";
    title.textContent = "📣 広告レポート取り込み";
    panel.appendChild(title);

    const msg = document.createElement("div");
    msg.style.cssText = "color:#475569;margin-bottom:6px;font-size:12px";
    msg.textContent = status || (cfg.token
      ? "広告の画面を開くと、実績をツールへ取り込みます"
      : "まず「設定」でトークンを入れてください");
    panel.appendChild(msg);

    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";
    row.appendChild(mk(busy ? "取り込み中…" : "今すぐ取り込む",
      busy ? "#94a3b8" : "#2563eb", () => run(true)));
    row.appendChild(mk(cfg.auto === false ? "自動：切" : "自動：入",
      cfg.auto === false ? "#94a3b8" : "#16a34a", toggleAuto));
    row.appendChild(mk("設定", "#64748b", configure));
    row.appendChild(mk("状況をコピー", "#b45309", copyNotes));
    panel.appendChild(row);
  }

  function start() {
    render();
    run(false);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
