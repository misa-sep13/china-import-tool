// RMSの画面で「ダウンロード」を押したときに流れるリクエストを見て、
// 同じCSVをこちらでも受け取るためのスクリプト。
//
// 勝手にページを次々取りに行くようなことはしない。押されたダウンロードと
// 同じものを1回取り直すだけなので、RMSへのアクセスは普通に使うのと
// ほとんど変わらない。
(function () {
  const MAX = 30 * 1024 * 1024;

  const send = (msg) => {
    try {
      window.postMessage(Object.assign({ __rmsAds: true }, msg), "*");
    } catch (e) {
      // 送れないときは諦める。RMSの画面の動きには一切影響させない
    }
  };

  const note = (text) => send({ kind: "note", text: String(text).slice(0, 300) });

  const b64 = (buf) => {
    const bytes = new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(s);
  };

  // 添付ファイルらしい応答かどうか。CSVの中身そのものも見る
  const looksAttachment = (ctype, cdisp) => {
    const t = (ctype || "").toLowerCase();
    const d = (cdisp || "").toLowerCase();
    return (
      t.includes("csv") ||
      t.includes("excel") ||
      t.includes("spreadsheet") ||
      t.includes("octet-stream") ||
      d.includes("attachment")
    );
  };

  const looksTable = (buf) => {
    if (buf.byteLength < 50 || buf.byteLength > MAX) return false;
    const head = new Uint8Array(buf.slice(0, 600));
    let s = "";
    for (let i = 0; i < head.length; i++) s += String.fromCharCode(head[i]);
    if (/^\s*[<{]/.test(s)) return false;         // HTMLやJSONは違う
    if (s.startsWith("PK")) return true;          // xlsx
    return s.includes(",") || s.includes("\t");
  };

  const nameFrom = (cdisp, url) => {
    const m = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(cdisp || "");
    if (m) {
      try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
    }
    const last = String(url || "").split(/[?#]/)[0].split("/").pop();
    return last && /\.(csv|tsv|xlsx?)$/i.test(last) ? last : "rpp-report.csv";
  };

  // 同じものを二度送らないための目印
  const seen = new Set();

  const offer = (buf, name, url, req) => {
    const key = `${name}:${buf.byteLength}`;
    if (seen.has(key)) return;
    seen.add(key);
    send({ kind: "file", name, url: String(url).slice(0, 300),
           size: buf.byteLength, b64: b64(buf), request: req || null });
  };

  // 押されたダウンロードと同じリクエストをもう一度出して、中身を受け取る
  async function replay(req, quiet) {
    try {
      const init = { method: req.method || "GET", credentials: "include" };
      if (init.method !== "GET" && req.body != null) {
        init.body = req.body;
        if (req.contentType) init.headers = { "Content-Type": req.contentType };
      }
      const res = await fetch(req.url, init);
      const ctype = res.headers.get("content-type") || "";
      const cdisp = res.headers.get("content-disposition") || "";
      const buf = await res.arrayBuffer();
      if (!looksAttachment(ctype, cdisp) && !looksTable(buf)) {
        if (!quiet) note(`ファイルではない応答でした（${ctype || "種類不明"}）`);
        return false;
      }
      offer(buf, nameFrom(cdisp, req.url), req.url, req);
      return true;
    } catch (e) {
      if (!quiet) note(`取り直しに失敗しました: ${e}`);
      return false;
    }
  }

  // パネルの「前と同じ条件でもう一度」から呼ばれる
  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (d && d.__rmsAdsReplay && d.request) replay(d.request, false);
  });

  // ---- fetch を包む（画面の中で取りに行く作りのとき） ----
  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = async function (...args) {
      const res = await origFetch.apply(this, args);
      try {
        const url = (args[0] && args[0].url) || String(args[0] || "");
        const ctype = res.headers.get("content-type") || "";
        const cdisp = res.headers.get("content-disposition") || "";
        if (looksAttachment(ctype, cdisp)) {
          res.clone().arrayBuffer().then((buf) => {
            if (looksTable(buf)) offer(buf, nameFrom(cdisp, url), url, null);
          }).catch(() => {});
        }
      } catch (e) {}
      return res;
    };
  }

  // ---- XMLHttpRequest を包む ----
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__rmsReq = { url: String(url), method: String(method || "GET").toUpperCase() };
    return origOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    try {
      if (this.__rmsReq && typeof args[0] === "string") {
        this.__rmsReq.body = args[0];
      }
    } catch (e) {}
    this.addEventListener("load", () => {
      try {
        const ctype = this.getResponseHeader("content-type") || "";
        const cdisp = this.getResponseHeader("content-disposition") || "";
        // XHRの文字列は文字化けしていることがあるので、そのまま使わず取り直す
        if (looksAttachment(ctype, cdisp) && this.__rmsReq) replay(this.__rmsReq, true);
      } catch (e) {}
    });
    return origSend.apply(this, args);
  };

  // ---- フォーム送信（画面が画面ごと遷移して落とす作りのとき） ----
  const fromForm = (form) => {
    const method = (form.method || "GET").toUpperCase();
    const enc = (form.enctype || "").toLowerCase();
    const fd = new FormData(form);
    const req = { url: form.action || location.href, method };
    if (method === "GET") {
      const q = new URLSearchParams();
      for (const [k, v] of fd.entries()) if (typeof v === "string") q.append(k, v);
      req.url += (req.url.includes("?") ? "&" : "?") + q.toString();
    } else if (enc.includes("multipart")) {
      req.body = fd;  // multipartはfetchが境界を付けてくれる
    } else {
      const q = new URLSearchParams();
      for (const [k, v] of fd.entries()) if (typeof v === "string") q.append(k, v);
      req.body = q.toString();
      req.contentType = "application/x-www-form-urlencoded";
    }
    return req;
  };

  document.addEventListener("submit", (ev) => {
    try {
      const form = ev.target;
      if (!(form instanceof HTMLFormElement)) return;
      // 画面の動きは邪魔しない。同じ内容をこちらでも取るだけ
      replay(fromForm(form), true);
    } catch (e) {}
  }, true);

  const origSubmit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () {
    try { replay(fromForm(this), true); } catch (e) {}
    return origSubmit.apply(this, arguments);
  };

  // ---- ダウンロードのリンク ----
  document.addEventListener("click", (ev) => {
    try {
      const a = ev.target && ev.target.closest && ev.target.closest("a[href]");
      if (!a) return;
      const href = a.getAttribute("href") || "";
      if (/^(#|javascript:)/i.test(href)) return;
      if (a.hasAttribute("download") ||
          /download|csv|tsv|report|dl/i.test(href)) {
        replay({ url: a.href, method: "GET" }, true);
      }
    } catch (e) {}
  }, true);
})();
