// CSVを輸入管理ツールへ送る係。
// RMSの画面から直接送ると別ドメイン扱いで弾かれるので、ここから送る。
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.type !== "upload") return;
  (async () => {
    try {
      const bin = atob(msg.b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);

      const fd = new FormData();
      fd.append("file", new Blob([bytes], { type: "text/csv" }),
        msg.name || "rpp-report.csv");

      const res = await fetch(`${msg.backend}/api/rakuten/ads/import`, {
        method: "POST",
        headers: { Authorization: `Bearer ${msg.token}` },
        body: fd,
      });
      const text = await res.text();
      let data = null;
      try { data = JSON.parse(text); } catch (e) {}
      if (!res.ok) {
        const err = (data && data.detail) || text.slice(0, 200);
        await chrome.storage.local.set({
          last_result: { text: `送信できませんでした：${err}`, at: Date.now() } });
        reply({ ok: false, error: err });
        return;
      }
      const kind = data && data.kind === "product" ? "商品ごと" : "毎日の消化";
      await chrome.storage.local.set({
        last_result: {
          text: `取り込みました：${kind} ${(data && data.saved) || 0}行`,
          at: Date.now(),
        },
      });
      reply({ ok: true, data });
    } catch (e) {
      reply({ ok: false, error: String(e) });
    }
  })();
  return true;   // 非同期で返す
});
