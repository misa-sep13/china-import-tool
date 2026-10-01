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

  // 画面が出している通信。どこを叩けばレポートが作れるのかを知るために残す
  const traffic = [];
  const apiJson = [];   // /rpp/api/ の応答。履歴の中身がここに入っている
  const apiCalls = [];  // /rpp/api/ へ出したもの。レポートの作り方がここに出る

  // レポートを作らせている呼び出しかどうか
  const looksGenerate = (method, url) =>
    String(method).toUpperCase() === "POST" &&
    /\/rpp\/api\//.test(String(url)) &&
    /report|item|download|csv/i.test(String(url));

  const keepCall = (method, url, body, contentType) => {
    if (!/\/rpp\/api\//.test(String(url))) return;
    const call = { method: String(method || "GET").toUpperCase(),
                   url: new URL(String(url), location.href).href,
                   body: typeof body === "string" ? body.slice(0, 4000) : null,
                   contentType: contentType || null };
    apiCalls.push(call);
    if (apiCalls.length > 10) apiCalls.shift();
    // 「全商品レポートダウンロード」を押したときの呼び出しを覚えておく。
    // 次からは画面のボタンに頼らず、これと同じものを出せばよい
    if (looksGenerate(call.method, call.url)) send({ kind: "learn", call });
  };
  const keepJson = (url, text) => {
    if (!/\/rpp\/api\//.test(String(url))) return;
    apiJson.push({ url: String(url).slice(0, 160), body: String(text).slice(0, 6000) });
    if (apiJson.length > 6) apiJson.shift();
  };
  const logReq = (method, url, status, ctype) => {
    traffic.push(`${method} ${String(url).slice(0, 160)} → ${status || "?"} ${ctype || ""}`);
    if (traffic.length > 60) traffic.shift();
  };

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
        const init = args[1] || {};
        const method = init.method || (args[0] && args[0].method) || "GET";
        logReq(method, url, res.status, ctype);
        let sentType = null;
        try {
          const h = new Headers(init.headers || {});
          sentType = h.get("content-type");
        } catch (e) {}
        keepCall(method, url, init.body, sentType);
        if (ctype.includes("json")) {
          res.clone().text().then((t) => keepJson(url, t)).catch(() => {});
        }
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
  const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    try {
      if (this.__rmsReq && String(k).toLowerCase() === "content-type") {
        this.__rmsReq.contentType = v;
      }
    } catch (e) {}
    return origSetHeader.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    try {
      if (this.__rmsReq && typeof args[0] === "string") {
        this.__rmsReq.body = args[0];
      }
      if (this.__rmsReq) {
        keepCall(this.__rmsReq.method, this.__rmsReq.url,
                 this.__rmsReq.body, this.__rmsReq.contentType);
      }
    } catch (e) {}
    this.addEventListener("load", () => {
      try {
        const ctype = this.getResponseHeader("content-type") || "";
        const cdisp = this.getResponseHeader("content-disposition") || "";
        if (this.__rmsReq) {
          logReq(this.__rmsReq.method, this.__rmsReq.url, this.status, ctype);
          if (ctype.includes("json") &&
              (this.responseType === "" || this.responseType === "text")) {
            keepJson(this.__rmsReq.url, this.responseText);
          }
        }
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

  const squash = (t) => String(t || "").replace(/\s+/g, "");

  const findButton = (label) =>
    Array.from(document.querySelectorAll(
      'input[type="submit"],input[type="button"],button,a[role="button"]'))
      .find((b) => squash(b.value || b.textContent).includes(label));

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---- レポート画面（/rpp/reports） ----
  //
  // この画面はフォームではなく、押すと画面の中で申し込む作り。条件を外から
  // 組み立てても通らないので、人と同じ順で押す。
  // 「全商品レポートダウンロード」は検索するまで押せないので、先に検索する。
  async function askReport(known) {
    // 一度でも押してあれば、その呼び出しをそのまま出す。
    // 画面のボタンは検索の具合で押せないことがあるので、こちらが確実
    if (known && known.url) {
      try {
        const init = { method: known.method || "POST", credentials: "include" };
        if (known.body != null) init.body = known.body;
        if (known.contentType) init.headers = { "Content-Type": known.contentType };
        const res = await fetch(known.url, init);
        if (res.ok) { send({ kind: "asked", ok: true }); return; }
        note(`覚えていた申し込みが通りませんでした（${res.status}）`);
      } catch (e) {
        note(`覚えていた申し込みに失敗しました: ${e}`);
      }
    }

    const dl = findButton("全商品レポートダウンロード");
    if (!dl) {
      send({ kind: "asked", ok: false,
             why: "全商品レポートダウンロードのボタンが見つかりませんでした" });
      return;
    }
    if (dl.disabled) {
      const search = findButton("この条件で検索");
      if (search) {
        send({ kind: "progress", text: "この条件で検索しています…" });
        try { search.click(); } catch (e) {}
      }
      for (let i = 0; i < 40 && dl.disabled; i++) await sleep(1000);
    }
    if (dl.disabled) {
      send({ kind: "asked", ok: false,
             why: "検索しても、ダウンロードのボタンが押せるようになりませんでした" });
      return;
    }
    try {
      dl.click();
      send({ kind: "asked", ok: true });
    } catch (e) {
      send({ kind: "asked", ok: false, why: `押せませんでした: ${e}` });
    }
  }

  // ---- ダウンロード履歴（/rpp/download） ----
  //
  // ここも画面の中で組み立てる作りなので、裏でHTMLを読んでも中身が無い。
  // 実際に開いたこの画面から取る。

  // 表の行から「ダウンロード」の押せるところを拾う。
  // since を渡すと、その時刻より後に出来た「完了」の行だけにする
  function rows(since) {
    const out = [];
    document.querySelectorAll("tr").forEach((tr) => {
      const text = tr.textContent || "";
      const ctl = Array.from(tr.querySelectorAll('a,button,[role="button"]'))
        .find((el) => squash(el.value || el.textContent) === "ダウンロード"
                      && !el.disabled);
      if (!ctl) return;
      if (since) {
        if (!text.includes("完了")) return;
        const m = text.match(/(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
        if (!m) return;
        const at = new Date(+m[1], +m[2] - 1, +m[3],
                            +m[4], +m[5], +m[6]).getTime();
        if (at < since) return;
      }
      out.push(ctl);
    });
    return out;
  }

  // リンクなら取りに行く。そうでなければ画面のボタンを押して、
  // 流れてきたCSVを拾う
  async function take(controls) {
    const was = seen.size;
    for (const el of controls) {
      const href = el.getAttribute && el.getAttribute("href");
      if (href && !/^(#|javascript:)/i.test(href)) {
        await replay({ url: new URL(href, location.href).href, method: "GET" },
                     true);
      } else {
        try { el.click(); } catch (e) {}
        await sleep(2500);
      }
    }
    await sleep(2500);
    return seen.size - was;
  }

  // 控えたJSONの中から、ファイルらしいURLを拾う
  function urlsFromJson() {
    const out = [];
    const walk = (v) => {
      if (typeof v === "string") {
        if (/^https?:\/\//.test(v) &&
            /\.(zip|csv|tsv|xlsx?)(\?|$)/i.test(v)) out.push(v);
        else if (/^\/[^\s"]*\.(zip|csv|tsv|xlsx?)(\?|$)/i.test(v)) {
          out.push(new URL(v, location.origin).href);
        }
      } else if (v && typeof v === "object") {
        Object.values(v).forEach(walk);
      }
    };
    apiJson.forEach((a) => {
      try { walk(JSON.parse(a.body)); } catch (e) {}
    });
    return Array.from(new Set(out));
  }

  async function grabHistory(limit, since) {
    const max = limit || 6;
    // 申し込んだ直後なら、出来上がるまで待つ
    const deadline = since ? Date.now() + 4 * 60 * 1000 : 0;
    for (;;) {
      const direct = urlsFromJson().slice(0, max);
      if (direct.length) {
        let got = 0;
        for (const u of direct) {
          if (await replay({ url: u, method: "GET" }, true)) got++;
        }
        if (got) { send({ kind: "auto-done", got }); return; }
      }
      const found = rows(since).slice(0, max);
      if (found.length) {
        const got = await take(found);
        if (got) { send({ kind: "auto-done", got }); return; }
      }
      if (Date.now() > deadline) {
        send({ kind: "auto-done", got: 0,
               why: since ? "レポートが出来上がりませんでした"
                          : "履歴に取れるものがありませんでした" });
        return;
      }
      send({ kind: "progress", text: "出来上がるのを待っています…" });
      const refresh = findButton("更新");
      if (refresh) { try { refresh.click(); } catch (e) {} }
      await sleep(12000);
    }
  }

  const guard = (fn) => fn().catch((e) => {
    send({ kind: "auto-done", got: 0, why: `途中で止まりました: ${e}` });
  });

  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (d && d.__rmsAdsAsk) {
      // 画面が出来上がってから。遅れて組み立てられる画面があるので少し待つ
      setTimeout(() => guard(() => askReport(d.known)), 1200);
    }
    if (d && d.__rmsAdsHistory) {
      setTimeout(() => guard(() => grabHistory(d.limit, d.since)), 1500);
    }
    if (d && d.__rmsAdsDump) {
      // 画面の作りをそのまま渡すための手がかり
      const btn = findButton("全商品レポートダウンロード")
        || findButton("この条件でダウンロード");
      const form = btn && btn.form;
      send({
        kind: "dump",
        text: JSON.stringify({
          url: location.href,
          button: btn ? (btn.outerHTML || "").slice(0, 300) : null,
          form: form ? { action: form.action, method: form.method,
            fields: Array.from(form.elements).filter((e) => e.name).map((e) =>
              `${e.name}=${e.type === "radio" || e.type === "checkbox"
                ? `${e.value}${e.checked ? "(選択中)" : ""}` : e.value}`
              .slice(0, 60)) } : null,
          traffic,
          apiCalls,
          apiJson,
          links: Array.from(document.querySelectorAll("a"))
            .filter((a) => squash(a.textContent).includes("ダウンロード"))
            .slice(0, 6).map((a) => (a.outerHTML || "").slice(0, 200)),
        }, null, 2),
      });
    }
  });

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
