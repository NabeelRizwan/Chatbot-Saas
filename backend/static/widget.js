(function () {
  const script = document.currentScript;
  const API_KEY = script.dataset.apiKey;
  const API_URL = "https://chatbot-saas-y5z8.onrender.com/chat/";

  // 💬 Floating Button
  const button = document.createElement("div");
  button.innerHTML = "💬";
  Object.assign(button.style, {
    position: "fixed",
    bottom: "20px",
    right: "20px",
    width: "60px",
    height: "60px",
    background: "#007bff",
    color: "white",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    zIndex: "9999",
    fontSize: "24px",
    boxShadow: "0 4px 10px rgba(0,0,0,0.2)"
  });

  document.body.appendChild(button);

  // 📦 Chat Container
  const box = document.createElement("div");
  Object.assign(box.style, {
    position: "fixed",
    bottom: "90px",
    right: "20px",
    width: "320px",
    height: "420px",
    background: "white",
    borderRadius: "10px",
    display: "none",
    flexDirection: "column",
    overflow: "hidden",
    zIndex: "9999",
    boxShadow: "0 4px 20px rgba(0,0,0,0.2)"
  });

  box.innerHTML = `
    <div style="background:#007bff;color:white;padding:10px;font-weight:bold;">
      AI Assistant
    </div>
    <div id="msgs" style="flex:1;padding:10px;overflow-y:auto;font-size:14px;"></div>
    <input id="inp" placeholder="Type a message..." 
      style="border:none;border-top:1px solid #eee;padding:10px;width:100%;outline:none;">
  `;

  document.body.appendChild(box);

  const input = box.querySelector("#inp");
  const msgs = box.querySelector("#msgs");

  // Toggle chat
  button.onclick = () => {
    box.style.display = box.style.display === "none" ? "flex" : "none";
  };

  // Add message helper
  function addMessage(text, sender) {
    const div = document.createElement("div");
    div.innerText = text;
    div.style.margin = "5px 0";
    div.style.padding = "8px";
    div.style.borderRadius = "8px";
    div.style.maxWidth = "80%";

    if (sender === "user") {
      div.style.background = "#007bff";
      div.style.color = "white";
      div.style.marginLeft = "auto";
    } else {
      div.style.background = "#f1f1f1";
    }

    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  // Send message
  input.addEventListener("keypress", async (e) => {
    if (e.key === "Enter") {
      const text = input.value.trim();
      if (!text) return;

      addMessage(text, "user");
      input.value = "";

      const loading = document.createElement("div");
      loading.innerText = "Typing...";
      msgs.appendChild(loading);

      try {
        const res = await fetch(API_URL, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            api_key: API_KEY,
            message: text
          })
        });

        const data = await res.json();
        loading.remove();

        addMessage(data.reply || "Error", "bot");
      } catch (err) {
        loading.remove();
        addMessage("Server error", "bot");
      }
    }
  });
})();
