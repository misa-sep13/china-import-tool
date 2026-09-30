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

  const setStatus = (text) => { status = text; render(); };

  async function upload(file) {
    const cfg = await chrome.storage.local.get(["backend", "token"]);
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
    const text = JSON.stringify(
      { url: location.href, notes: notes.slice(-20), lastRequest }, null, 2);
    navigator.clipboard.writeText(text).then(
      () => alert("状況をコピーしました。開発側に渡してください。"),
      () => alert(text.slice(0, 1500)));
  }

  async function toggleAuto() {
    const cfg = await chrome.storage.local.get(["auto"]);
    const next = cfg.auto === false;
    await chrome.storage.local.set({ auto: next });
    setStatus(next ? "自動で送ります" : "確認してから送ります");
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
      (cfg.token ? "「この条件でダウンロード」を押すと、同じCSVをツールへ送ります"
                 : "まず「設定」でトークンを入れてください");
    panel.appendChild(msg);

    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";
    if (pending) row.appendChild(mk("ツールに送る", "#2563eb", () => upload(pending)));
    if (lastRequest) row.appendChild(mk("前と同じ条件でもう一度", "#0f766e", again));
    row.appendChild(mk(cfg.auto === false ? "自動送信：切" : "自動送信：入",
      cfg.auto === false ? "#94a3b8" : "#16a34a", toggleAuto));
    row.appendChild(mk("設定", "#64748b", configure));
    row.appendChild(mk("状況をコピー", "#b45309", copyDiagnostics));
    panel.appendChild(row);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
