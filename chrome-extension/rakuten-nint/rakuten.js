(function() {
  const processedUrls = new Set();

  const observer = new MutationObserver(() => {
    document.querySelectorAll('a').forEach(link => {
      const url = link.href;
      if (!url.includes("item.rakuten.co.jp")) return;
      if (processedUrls.has(url)) return;

      const match = url.match(/item\.rakuten\.co\.jp\/([^\/]+)\/([^\/?#]+)/);
      if (!match) return;

      processedUrls.add(url);

      const shop = match[1];
      const code = match[2];
      const nintUrl = `https://ec.nint.jp/v/item/detail?Cpage=rakuten&catalogId=0&unique_item_code=1%23%3A%40${shop}%23%3A%40${code}`;
      const itemUrl = url;

      const wrapper = document.createElement("div");
      wrapper.style.marginTop = "6px";
      wrapper.style.display = "flex";
      wrapper.style.gap = "6px";
      wrapper.style.zIndex = "9999";
      wrapper.style.position = "relative";

      const createButton = (text, background, clickHandler) => {
        const btn = document.createElement("div");
        btn.style.padding = "6px 0";
        btn.style.background = background;
        btn.style.color = "#fff";
        btn.style.fontSize = "13px";
        btn.style.borderRadius = "6px";
        btn.style.cursor = "pointer";
        btn.style.width = "100px";
        btn.style.textAlign = "center";
        btn.textContent = text;
        btn.addEventListener("click", clickHandler);
        return btn;
      };

      const btnNint = createButton("Nint", "#004aad", e => {
        e.preventDefault();
        e.stopPropagation();
        window.open(nintUrl, "_blank");
      });

      const btnNintItem = createButton("Nint+商品", "linear-gradient(to right, #004aad 50%, #cc0000 50%)", e => {
        e.preventDefault();
        e.stopPropagation();
        window.open(nintUrl, "_blank");
        window.open(itemUrl, "_blank");
      });

      const btnItemOnly = createButton("商品", "#cc0000", e => {
        e.preventDefault();
        e.stopPropagation();
        window.open(itemUrl, "_blank");
      });

      wrapper.appendChild(btnNint);
      wrapper.appendChild(btnNintItem);
      wrapper.appendChild(btnItemOnly);

      // タイトルリンクの後に挿入
      link.insertAdjacentElement("afterend", wrapper);
    });
  });

  observer.observe(document.body, { childList: true, subtree: true });
})();