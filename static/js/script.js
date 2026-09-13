// ============ Theme toggle (dark / light) ============
document.addEventListener("DOMContentLoaded", () => {
  const root = document.documentElement;
  const themeToggle = document.getElementById("themeToggle");
  const themeIcon = document.getElementById("themeIcon");

  function setIcon(theme) {
    if (!themeIcon) return;
    themeIcon.className = theme === "dark" ? "bi bi-sun-fill" : "bi bi-moon-stars-fill";
  }
  setIcon(root.getAttribute("data-theme"));

  if (themeToggle) {
    themeToggle.addEventListener("click", async () => {
      const res = await fetch("/toggle-theme", { method: "POST" });
      const data = await res.json();
      root.setAttribute("data-theme", data.theme);
      setIcon(data.theme);
    });
  }

  // ============ Sidebar toggle (mobile) ============
  const sidebar = document.getElementById("sidebar");
  const sidebarToggle = document.getElementById("sidebarToggle");
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
  }

  // ============ Send mode toggle (compose page) ============
  const sendModeBtns = document.querySelectorAll("[data-send-mode]");
  const scheduleFields = document.getElementById("scheduleFields");
  const sendModeInput = document.getElementById("send_mode_input");
  sendModeBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      sendModeBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const mode = btn.dataset.sendMode;
      if (sendModeInput) sendModeInput.value = mode;
      if (scheduleFields) scheduleFields.style.display = mode === "schedule" ? "block" : "none";
    });
  });

  // ============ Load template into compose form ============
  const templateSelect = document.getElementById("templateSelect");
  if (templateSelect) {
    templateSelect.addEventListener("change", async () => {
      const id = templateSelect.value;
      if (!id) return;
      const res = await fetch(`/templates/${id}/json`);
      const data = await res.json();
      document.getElementById("subject").value = data.subject;
      document.getElementById("body").value = data.body;
    });
  }

  // ============ Send test email (AJAX) ============
  const testForm = document.getElementById("testEmailForm");
  if (testForm) {
    testForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = testForm.querySelector("button[type=submit]");
      const originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Sending...';

      const formData = new FormData(testForm);
      const res = await fetch("/send-test", { method: "POST", body: formData });
      const data = await res.json();

      const resultBox = document.getElementById("testEmailResult");
      resultBox.style.display = "block";
      resultBox.className = "alert " + (data.success ? "alert-success" : "alert-danger");
      resultBox.textContent = data.message;

      btn.disabled = false;
      btn.innerHTML = originalText;
    });
  }

  // ============ Character / recipient counter on compose ============
  const recipientsField = document.getElementById("recipients");
  const recipientCount = document.getElementById("recipientCount");
  if (recipientsField && recipientCount) {
    const updateCount = () => {
      const raw = recipientsField.value.trim();
      const count = raw ? raw.split(/[\n,]/).map((s) => s.trim()).filter(Boolean).length : 0;
      recipientCount.textContent = count;
    };
    recipientsField.addEventListener("input", updateCount);
    updateCount();
  }
});
