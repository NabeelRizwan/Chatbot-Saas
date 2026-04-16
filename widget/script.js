(function () {
  const script = document.currentScript;
  const API_KEY = script.dataset.apiKey;
  const API_URL = "https://YOUR_BACKEND_URL/chat/";

  const box = document.createElement("div");
  box.innerHTML = `
    <div style="position:fixed;bottom:20px;right:20px;width:300px;background:white;border:1px solid #ccc;">
      <div id="msgs" style="height:200px;overflow:auto;"></div>
      <input id="inp" placeholder="Ask..." style="width:100%;">
    </div>
  `;
  document.body.appendChild(box);

  const input = box.querySelector("#inp");
  const msgs = box.querySelector("#msgs");

  input.addEventListener("keypress", async (e) => {
    if (e.key === "Enter") {
      const text = input.value;
      msgs.innerHTML += `<div>You: ${text}</div>`;

      const res = await fetch(API_URL, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          api_key: API_KEY,
          message: text
        })
      });

      const data = await res.json();
      msgs.innerHTML += `<div>Bot: ${data.reply}</div>`;
      input.value = "";
    }
  });
})();
