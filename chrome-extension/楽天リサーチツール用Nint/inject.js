// Nintのページ自身が取得したデータを、その場で横から見るためのスクリプト。
//
// ここから新しいリクエストは一切出さない。ページが表示のために既に受け取った
// 応答を覗くだけなので、Nint側のアクセス数は普通に閲覧するのと変わらない。
// （規約でクローリング・スクレイピングが禁じられているため、こちらから
//   ページを次々に取りに行く作りにはしていない）
(function () {
  const post = (url, body) => {
    try {
      window.postMessage({ __nintCapture: true, url, body }, "*");
    } catch (e) {
      // 送れない場合は諦める。ページの表示には影響させない
    }
  };

  const looksInteresting = (text) =>
    typeof text === "string" &&
    text.length > 50 &&
    (text.includes("{") || text.includes("["));

  // fetch を包む
  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = async function (...args) {
      const res = await origFetch.apply(this, args);
      try {
        const url = (args[0] && args[0].url) || String(args[0] || "");
        res.clone().text().then((t) => {
          if (looksInteresting(t)) post(url, t);
        }).catch(() => {});
      } catch (e) {}
      return res;
    };
  }

  // XMLHttpRequest を包む
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__nintUrl = url;
    return origOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", () => {
      try {
        const t =
          this.responseType === "" || this.responseType === "text"
            ? this.responseText
            : null;
        if (looksInteresting(t)) post(this.__nintUrl || "", t);
      } catch (e) {}
    });
    return origSend.apply(this, args);
  };
})();
