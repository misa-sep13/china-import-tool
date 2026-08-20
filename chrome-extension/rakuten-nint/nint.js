// Nintの画面で、ページが受け取ったデータから「商品」と「月別の売上・販売個数」を
// 取り出してリサーチツールへ送る。
//
// 一覧画面を開けば、その画面に載っている商品がまとめて入る（1商品ずつにはならない）。
// Nintへのアクセスはこちらからは一切増やさない。
(function () {
  const DEFAULT_BACKEND = "https://china-import-tool.onrender.com";

  // ページ側のfetch/XHRを包むスクリプトを、ページの文脈で動かす
  const s = document.createElement("script");
  s.src = chrome.runtime.getURL("inject.js");
  (document.head || document.documentElement).appendChild(s);
  s.onload = () => s.remove();

  const captured = [];      // 取り出せた商品
  const seenUrls = [];      // 診断用：どこから来たデータか
  let panel = null;

  // ---- データの取り出し ----

  // "1#:@luckyhill#:@nz-48ss" や商品URLから "ショップ名/商品コード" を作る
  const urlKeyFrom = (text) => {
    if (typeof text !== "string") return null;
    let m = text.match(/item\.rakuten\.co\.jp\/([^/?#"]+)\/([^/?#"]+)/);
    if (m) return `${m[1]}/${m[2]}`;
    m = text.match(/#:@([^#"]+)#:@([^#"&]+)/);
    if (m) return `${m[1]}/${m[2]}`;
    return null;
  };

  const toNum = (v) => {
    if (typeof v === "number") return Math.round(v);
    if (typeof v === "string") {
      const n = Number(v.replace(/[,\s円個]/g, ""));
      if (!Number.isNaN(n)) return Math.round(n);
    }
    return null;
  };

  // "202604" / "2026-04" / "2026/04" を 202604 に揃える
  const normalizeYm = (k) => {
    const s = String(k);
    let m = s.match(/(20\d{2})[-/]?(0[1-9]|1[0-2])/);
    return m ? `${m[1]}${m[2]}` : null;
  };

  // オブジェクトの中から、年月をキーにした数値の並びを拾う
  const monthsFromObject = (obj) => {
    const amounts = {}, units = {};
    for (const [k, v] of Object.entries(obj)) {
      const ym = normalizeYm(k);
      if (!ym) continue;
      const n = toNum(v);
      if (n === null) continue;
      if (/個|units|qty|count|数/i.test(k)) units[ym] = n;
      else amounts[ym] = n;
    }
    const yms = new Set([...Object.keys(amounts), ...Object.keys(units)]);
    return [...yms].sort().map((ym) => ({
      ym,
      sales_amount: amounts[ym] ?? null,
      units: units[ym] ?? null,
    }));
  };

  // JSONを再帰的に見て、商品らしいオブジェクトを集める
  const scan = (node, depth = 0) => {
    if (!node || depth > 8) return;
    if (Array.isArray(node)) {
      node.forEach((v) => scan(v, depth + 1));
      return;
    }
    if (typeof node !== "object") return;

    const flat = JSON.stringify(node).slice(0, 4000);
    const key = urlKeyFrom(flat);
    if (key) {
      const months = monthsFromObject(node);
      if (months.length) {
        captured.push({
          url_key: key,
          item_name: node.itemName || node.item_name || node.name || node.商品名 || "",
          shop_name: node.shopName || node.shop_name || node.ショップ名 || "",
          item_url: (flat.match(/https?:\/\/item\.rakuten\.co\.jp\/[^"'\s]+/) || [null])[0],
          image_url: (flat.match(/https?:\/\/[^"'\s]*r10s\.jp[^"'\s]*/) || [null])[0],
          months,
        });
      }
    }
    Object.values(node).forEach((v) => scan(v, depth + 1));
  };

  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (!d || !d.__nintCapture) return;
    seenUrls.push(String(d.url).slice(0, 200));
    try {
      const before = captured.length;
      scan(JSON.parse(d.body));
      if (captured.length !== before) render();
      else render();
    } catch (e) {
      render();
    }
  });

  // ---- 画面 ----

  const dedup = () => {
    const map = new Map();
    captured.forEach((c) => map.set(c.url_key, c));
    return [...map.values()];
  };

  async function send() {
    const items = dedup();
    if (!items.length) return;
    const cfg = await chrome.storage.local.get(["backend", "token"]);
    const backend = cfg.backend || DEFAULT_BACKEND;
    if (!cfg.token) {
      alert("先にトークンを設定してください（パネルの「設定」から）");
      return;
    }
    try {
      const res = await fetch(`${backend}/api/research/nint/capture`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${cfg.token}`,
        },
        body: JSON.stringify({ items }),
      });
      const json = await res.json();
      alert(res.ok ? `${json.saved}件をツールに保存しました` : `失敗: ${JSON.stringify(json)}`);
    } catch (e) {
      alert(`送信に失敗しました: ${e}`);
    }
  }

  async function configure() {
    const cfg = await chrome.storage.local.get(["backend", "token"]);
    const backend = prompt("ツールのURL", cfg.backend || DEFAULT_BACKEND);
    if (backend === null) return;
    const token = prompt("サービストークン（AUTH_SERVICE_TOKEN）", cfg.token || "");
    if (token === null) return;
    await chrome.storage.local.set({ backend: backend.trim(), token: token.trim() });
    alert("保存しました");
  }

  // 取り出せなかったときに、どんなデータが来ていたかを共有するための診断用
  function copyDiagnostics() {
    const text = JSON.stringify({ url: location.href, endpoints: seenUrls.slice(0, 30) }, null, 2);
    navigator.clipboard.writeText(text).then(
      () => alert("診断情報をコピーしました。これを開発側に渡してください。"),
      () => alert(text.slice(0, 1500))
    );
  }

  function render() {
    if (!document.body) return;
    const items = dedup();
    if (!panel) {
      panel = document.createElement("div");
      panel.style.cssText =
        "position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#fff;" +
        "border:1px solid #cbd5e1;border-radius:8px;padding:10px 12px;font-size:13px;" +
        "box-shadow:0 4px 16px rgba(0,0,0,.18);font-family:sans-serif;min-width:220px";
      document.body.appendChild(panel);
    }
    panel.innerHTML = "";

    const title = document.createElement("div");
    title.style.cssText = "font-weight:700;margin-bottom:6px";
    title.textContent = items.length
      ? `売上データ ${items.length}件を検出`
      : "売上データを検出できていません";
    panel.appendChild(title);

    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";

    const mk = (label, bg, fn) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.style.cssText =
        `padding:5px 10px;border:none;border-radius:5px;cursor:pointer;font-size:12px;background:${bg};color:#fff`;
      b.onclick = fn;
      return b;
    };

    if (items.length) row.appendChild(mk("ツールに送る", "#2563eb", send));
    row.appendChild(mk("設定", "#64748b", configure));
    if (!items.length) row.appendChild(mk("診断情報をコピー", "#b45309", copyDiagnostics));
    panel.appendChild(row);
  }

  const boot = () => render();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
