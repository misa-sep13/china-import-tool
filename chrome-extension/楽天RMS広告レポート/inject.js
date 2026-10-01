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

  // ---- パフォーマンスレポートの画面を開いたら、自分で取りに行く ----
  //
  // 画面のボタンを押したときとまったく同じ内容のリクエストを組み立てて出す。
  // 画面の表示（選んである条件）は書き換えない。送る中身だけ差し替える。

  const squash = (t) => String(t || "").replace(/\s+/g, "");

  // そのラジオボタンに付いている文字。labelで囲ってある場合と、
  // 隣に文字が置いてあるだけの場合の両方を見る
  const labelOf = (input) => {
    if (input.id) {
      const l = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (l) return squash(l.textContent);
    }
    const wrap = input.closest("label");
    if (wrap) return squash(wrap.textContent);
    const next = input.nextSibling;
    if (next && next.textContent) return squash(next.textContent);
    return squash(input.parentElement && input.parentElement.textContent);
  };

  const findRadio = (form, label) =>
    Array.from(form.querySelectorAll('input[type="radio"]'))
      .find((r) => labelOf(r).includes(label));

  const findButton = (label) =>
    Array.from(document.querySelectorAll(
      'input[type="submit"],input[type="button"],button'))
      .find((b) => squash(b.value || b.textContent).includes(label));

  // フォームの中身をそのまま書き出す。overrides に入れた名前だけ差し替える
  const serialize = (form, overrides, button) => {
    const q = new URLSearchParams();
    for (const el of Array.from(form.elements)) {
      if (!el.name || el.disabled) continue;
      if (["submit", "button", "image", "file"].includes(el.type)) continue;
      if ((el.type === "checkbox" || el.type === "radio") && !el.checked) continue;
      if (Object.prototype.hasOwnProperty.call(overrides, el.name)) continue;
      if (el.multiple && el.selectedOptions) {
        for (const o of el.selectedOptions) q.append(el.name, o.value);
      } else {
        q.append(el.name, el.value);
      }
    }
    for (const [k, v] of Object.entries(overrides)) {
      if (v != null && k) q.append(k, v);
    }
    if (button && button.name) q.append(button.name, button.value || "");
    return q.toString();
  };

  const reqFrom = (form, overrides, button) => {
    const method = (form.method || "POST").toUpperCase();
    const body = serialize(form, overrides, button);
    let url = form.action || location.href;
    if (method === "GET") {
      url += (url.includes("?") ? "&" : "?") + body;
      return { url, method };
    }
    return { url, method, body,
             contentType: "application/x-www-form-urlencoded" };
  };

  // 集計期間の日付欄。YYYY-MM-DD が入っているものを前から2つ
  const dateFields = (form) =>
    Array.from(form.querySelectorAll("input"))
      .filter((i) => /^\d{4}-\d{2}-\d{2}$/.test(i.value || ""));

  async function autoRun(kinds, range) {
    const prodBtn = findButton("全商品レポートダウンロード");
    const dlBtn = findButton("この条件でダウンロード");
    const form = (dlBtn && dlBtn.form) || (prodBtn && prodBtn.form);
    if (!form) {
      note("ダウンロードのボタンが見つかりませんでした");
      return;
    }
    const dates = dateFields(form);
    const unitAll = findRadio(form, "すべての広告");
    const perDay = findRadio(form, "日ごとに表示");
    const perAll = findRadio(form, "全期間で表示");

    const withDates = (from, to) => {
      const o = {};
      if (dates[0] && dates[0].name) o[dates[0].name] = from;
      if (dates[1] && dates[1].name) o[dates[1].name] = to;
      return o;
    };

    let got = 0;
    if (kinds.includes("daily") && dlBtn && unitAll && perDay) {
      const o = withDates(range.daily_from, range.to);
      o[unitAll.name] = unitAll.value;
      o[perDay.name] = perDay.value;
      if (await replay(reqFrom(form, o, dlBtn), true)) got++;
      else note("毎日の消化が取れませんでした");
    }
    if (kinds.includes("product") && prodBtn) {
      const o = withDates(range.product_from, range.to);
      if (perAll) o[perAll.name] = perAll.value;
      if (await replay(reqFrom(form, o, prodBtn), true)) got++;
      else note("商品ごとが取れませんでした");
    }
    send({ kind: "auto-done", got });
  }

  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (d && d.__rmsAdsAuto && Array.isArray(d.kinds)) {
      // 画面が出来上がってから。遅れて組み立てられる画面があるので少し待つ
      setTimeout(() => autoRun(d.kinds, d.range || {}), 1200);
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
