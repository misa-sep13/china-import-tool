// RMSの広告（RPP）パフォーマンスレポートを落としたときに、同じCSVを
// 輸入管理ツールへ送る。落としたファイルを自分で開いて入れ直す手間を
// 無くすためのもの。
//
// 取るのは「ダウンロード」を押したときだけ。押していないのに裏で
// レポートを作りに行くようなことはしない。
(function () {
  const DEFAULT_BACKEND = "https://china-import-tool.onrender.com";
  const isTop = window.top === window;

  // ページ側のfetch/XHR・フォーム送信を見るスクリプトを差し込む
  const s = document.createElement("script");
  s.src = chrome.runtime.getURL("inject.js");
  (document.head || document.documentElement).appendChild(s);
  s.onload = () => s.remove();

  let panel = null;
  let status = "";          // 画面に出す一言
  let pending = null;       // まだ送っていないファイル
  let lastRequest = null;   // 「もう一度」で使う、直前のダウンロード条件
  const notes = [];         // 取れなかったときの手がかり
  let running = [];         // いま取りに行っている種類
  let dumpWaiter = null;    // 画面側が応えたかどうかの確認用

  const setStatus = (text) => { status = text; render(); };

  async function upload(file) {
    const cfg = await chrome.storage.local.get(["backend", "token", "sent"]);
    const sent = cfg.sent || [];
    if (sent.includes(file.name)) {
      setStatus(`${file.name} は取り込み済みです`);
      return;
    }
    if (!cfg.token) {
      pending = file;
      setStatus("トークンが未設定です。「設定」から入れてください");
      return;
    }
    setStatus(`${file.name} を送っています…`);
    try {
      const res = await chrome.runtime.sendMessage({
        type: "upload",
        backend: cfg.backend || DEFAULT_BACKEND,
        token: cfg.token,
        name: file.name,
        b64: file.b64,
      });
      if (res && res.ok) {
        const d = res.data || {};
        const kind = d.kind === "product" ? "商品ごと" : "毎日の消化";
        const missing = (d.missing || []).length
          ? `／見つからない列：${d.missing.join("、")}` : "";
        pending = null;
        await chrome.storage.local.set({ sent: sent.concat([file.name]).slice(-50) });
        setStatus(`取り込みました：${kind} ${d.saved}行${missing}`);
      } else {
        pending = file;
        setStatus(`送信できませんでした：${(res && res.error) || "理由不明"}`);
      }
    } catch (e) {
      pending = file;
      setStatus(`送信できませんでした：${e}`);
    }
  }

  window.addEventListener("message", async (ev) => {
    const d = ev.data;
    if (!d || !d.__rmsAds) return;
    if (d.kind === "note") { notes.push(d.text); render(); return; }
    if (d.kind === "progress") { setStatus(d.text); return; }
    if (d.kind === "asked") { afterAsk(d.ok, d.why); return; }
    if (d.kind === "learn" && d.call) {
      // 「全商品レポートダウンロード」を押したときの呼び出し。
      // 次からはこれを出せば、ボタンに頼らず作らせられる
      await chrome.storage.local.set({ generate_call: d.call });
      setStatus("レポートの作り方を覚えました");
      // 手で押したときは、そのまま履歴へ移って取り込む
      const cfg = await chrome.storage.local.get(["token", "auto"]);
      if (cfg.token && cfg.auto !== false) afterAsk(true);
      return;
    }
    if (d.kind === "dump") {
      if (dumpWaiter) { dumpWaiter(); dumpWaiter = null; }
      const text = [d.text, "--- 気づいたこと ---"]
        .concat(notes.slice(-20)).join(String.fromCharCode(10));
      navigator.clipboard.writeText(text).then(
        () => setStatus("画面の作りをコピーしました。貼って渡してください"),
        () => alert(text.slice(0, 2000)));
      return;
    }
    if (d.kind === "auto-done") {
      if (d.got) {
        const cur = (await chrome.storage.local.get(["auto_last"])).auto_last || {};
        running.forEach((k) => { cur[k] = Date.now(); });
        await chrome.storage.local.set({ auto_last: cur, auto_cooldown: 0 });
      } else {
        setStatus(`自動では取れませんでした（${d.why || "理由不明"}）`);
      }
      running = [];
      return;
    }
    if (d.kind !== "file") return;

    if (d.request) {
      lastRequest = d.request;
      // FormDataは持ち回せないので、文字列で組めたものだけ覚えておく
      if (typeof lastRequest.body !== "string" && lastRequest.body != null) {
        lastRequest = null;
      } else {
        chrome.storage.local.set({ last_request: lastRequest });
      }
    }

    const cfg = await chrome.storage.local.get(["auto"]);
    const file = { name: d.name, b64: d.b64, size: d.size };
    if (cfg.auto === false) {
      pending = file;
      setStatus(`${d.name} を受け取りました。「ツールに送る」を押してください`);
    } else {
      upload(file);
    }
  });

  // 別のフレームで送ったときも、上のパネルに結果を出す
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.last_result && isTop) {
      const r = changes.last_result.newValue || {};
      if (r.text) setStatus(r.text);
    }
    if (changes.last_request) lastRequest = changes.last_request.newValue || null;
  });

  async function configure() {
    const cfg = await chrome.storage.local.get(["backend", "token"]);
    const backend = prompt("輸入管理ツールのURL", cfg.backend || DEFAULT_BACKEND);
    if (backend === null) return;
    const token = prompt("サービストークン（AUTH_SERVICE_TOKEN）", cfg.token || "");
    if (token === null) return;
    await chrome.storage.local.set({
      backend: backend.trim().replace(/\/+$/, ""),
      token: token.trim(),
    });
    setStatus("保存しました");
    if (pending) upload(pending);
  }

  function again() {
    if (!lastRequest) return;
    setStatus("前と同じ条件で取り直しています…");
    window.postMessage({ __rmsAdsReplay: true, request: lastRequest }, "*");
  }

  function copyDiagnostics() {
    // 画面側の作り（ボタン・フォーム・履歴のリンク）も一緒に渡す。
    // ここが分からないと自動取り込みを直せない
    let answered = false;
    dumpWaiter = () => { answered = true; };
    window.postMessage({ __rmsAdsDump: true }, "*");
    setTimeout(() => {
      if (answered) return;
      // 画面側のスクリプトが動いていない。その事実ごと渡す
      const text = ["画面側のスクリプトが応えません（inject.jsが動いていない）",
        location.href, `いまの表示: ${status}`]
        .concat(notes.slice(-20)).join(String.fromCharCode(10));
      navigator.clipboard.writeText(text).then(
        () => setStatus("状況をコピーしました（画面側が応えていません）"),
        () => alert(text));
    }, 1500);
  }

  async function toggleAuto() {
    const cfg = await chrome.storage.local.get(["auto"]);
    const next = cfg.auto === false;
    await chrome.storage.local.set({ auto: next });
    setStatus(next ? "この画面を開いたら自動で取り込みます" : "自動取り込みを止めました");
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
    if (!isTop || !document.body) return;
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
    msg.textContent = status ||
      (cfg.token ? "パフォーマンスレポートの画面を開くと自動で取り込みます"
                 : "まず「設定」でトークンを入れてください");
    panel.appendChild(msg);

    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";
    if (pending) row.appendChild(mk("ツールに送る", "#2563eb", () => upload(pending)));
    if (lastRequest) row.appendChild(mk("前と同じ条件でもう一度", "#0f766e", again));
    row.appendChild(mk("今すぐ取り込む", "#2563eb", () => maybeAuto(true)));
    row.appendChild(mk(cfg.auto === false ? "自動：切" : "自動：入",
      cfg.auto === false ? "#94a3b8" : "#16a34a", toggleAuto));
    row.appendChild(mk("設定", "#64748b", configure));
    row.appendChild(mk("状況をコピー", "#b45309", copyDiagnostics));
    panel.appendChild(row);
  }

  // ---- 画面を開いたら自分で取りに行く ----
  //
  // 流れはこう：
  //   レポート画面 → 検索してダウンロードを押す → ダウンロード履歴へ移る
  //   → 出来上がるのを待って取り込む
  // 履歴の画面を開いただけのときは、並んでいるものをそのまま取り込む。
  const GAP_MS = 6 * 60 * 60 * 1000;
  const HISTORY = "/rpp/download";

  const onHistory = () => /\/rpp\/download(\/|$|\?)/.test(location.href);
  const onReports = () => /\/rpp\/reports/.test(location.href);

  async function maybeAuto(force) {
    const cfg = await chrome.storage.local.get(
      ["token", "auto", "auto_last", "auto_cooldown", "pending"]);
    if (!cfg.token) {
      if (force) setStatus("先に「設定」でトークンを入れてください");
      return;
    }
    if (!force && cfg.auto === false) return;

    if (onHistory()) {
      // 申し込んだ直後に移ってきたのなら、そのぶんが出来上がるのを待つ
      const p = cfg.pending;
      const fresh = p && Date.now() - p.at < 10 * 60 * 1000;
      await chrome.storage.local.remove("pending");
      setStatus(fresh ? "出来上がるのを待っています…"
                      : "履歴にあるレポートを取り込んでいます…");
      running = ["product"];
      window.postMessage({ __rmsAdsHistory: true, limit: fresh ? 2 : 6,
                           since: fresh ? p.at - 60000 : 0 }, "*");
      return;
    }
    if (!onReports()) return;

    const last = cfg.auto_last || {};
    const now = Date.now();
    // 失敗した直後に何度も申し込まないための間隔
    if (!force && now < (cfg.auto_cooldown || 0)) return;
    if (!force && now - (last.product || 0) < GAP_MS) return;

    running = ["product"];
    await chrome.storage.local.set({ auto_cooldown: now + 15 * 60 * 1000 });
    setStatus("レポートを申し込んでいます…");
    const known = (await chrome.storage.local.get(["generate_call"])).generate_call;
    window.postMessage({ __rmsAdsAsk: true, known: known || null }, "*");
  }

  // 申し込めたら、ダウンロード履歴へ移る（画面ごと開き直す）
  async function afterAsk(ok, why) {
    if (!ok) {
      setStatus(`申し込めませんでした（${why || "理由不明"}）`);
      return;
    }
    await chrome.storage.local.set({ pending: { at: Date.now() } });
    setStatus("ダウンロード履歴へ移ります…");
    location.href = new URL(HISTORY, location.origin).href;
  }

  // この画面は中で切り替わる作りなので、開き直さずに行き来することがある。
  // URLを見張って、移った先でも動くようにする
  let seenUrl = location.href;
  setInterval(() => {
    if (location.href === seenUrl) return;
    seenUrl = location.href;
    status = "";
    maybeAuto(false);
  }, 2000);

  function start() {
    render();
    maybeAuto();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
