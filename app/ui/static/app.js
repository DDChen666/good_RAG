const outputEl = document.getElementById("output");
const apiKeyInput = document.getElementById("api-key-input");

const state = {
  apiKey: localStorage.getItem("good_rag_api_key") || "",
};

const uploadState = {
  pdf: [],
  md: [],
};

const ACCEPT_MAP = {
  pdf: [".pdf"],
  md: [".md", ".markdown", ".mdown", ".txt"],
};

if (state.apiKey) {
  apiKeyInput.value = state.apiKey;
  apiKeyInput.type = "password";
}

function setOutput(title, data) {
  const timestamp = new Date().toLocaleString();
  const pretty = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  outputEl.textContent = `[${timestamp}] ${title}\n\n${pretty}`;
}

function buildHeaders(includeJson = true) {
  const headers = {};
  if (includeJson) {
    headers["Content-Type"] = "application/json";
  }
  if (state.apiKey) {
    headers["X-API-Key"] = state.apiKey;
  }
  return headers;
}

async function apiFetch(path, options = {}) {
  const opts = { ...options };
  const isFormData = typeof FormData !== "undefined" && opts.body instanceof FormData;
  const shouldSkipJson = options.skipJsonHeader || isFormData;
  opts.headers = { ...buildHeaders(!shouldSkipJson), ...(options.headers || {}) };

  if (opts.body && typeof opts.body !== "string" && !isFormData) {
    opts.body = JSON.stringify(opts.body);
  }

  const response = await fetch(path, opts);
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(typeof payload === "string" ? payload : JSON.stringify(payload));
  }
  return payload;
}

function parseList(value) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseCsv(value) {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function parseBoolean(value) {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

function hasAllowedExtension(file, type) {
  const lowered = file.name.toLowerCase();
  return ACCEPT_MAP[type].some((ext) => lowered.endsWith(ext));
}

function renderFileList(type) {
  const container = document.getElementById(`${type}-file-list`);
  container.innerHTML = "";

  uploadState[type].forEach((item) => {
    const li = document.createElement("li");
    li.className = "file-pill";
    li.dataset.uploadId = item.upload_id;

    const nameSpan = document.createElement("span");
    nameSpan.className = "file-pill__name";
    nameSpan.textContent = item.original_name;

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "file-pill__remove";
    removeBtn.setAttribute("aria-label", `移除 ${item.original_name}`);
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      removeUpload(type, item.upload_id);
    });

    li.appendChild(nameSpan);
    li.appendChild(removeBtn);
    container.appendChild(li);
  });
}

async function removeUpload(type, uploadId) {
  uploadState[type] = uploadState[type].filter((item) => item.upload_id !== uploadId);
  renderFileList(type);

  try {
    await apiFetch(`/upload/${encodeURIComponent(uploadId)}`, {
      method: "DELETE",
      skipJsonHeader: true,
    });
  } catch (error) {
    setOutput("刪除檔案時發生錯誤", error.message || String(error));
  }
}

async function uploadFile(type, file) {
  if (!hasAllowedExtension(file, type)) {
    setOutput("上傳失敗", `不支援的檔案格式：${file.name}`);
    return;
  }

  const form = new FormData();
  form.append("file", file, file.name);

  try {
    const data = await apiFetch("/upload", {
      method: "POST",
      body: form,
      skipJsonHeader: true,
    });
    uploadState[type].push(data);
    renderFileList(type);
  } catch (error) {
    setOutput("檔案上傳失敗", error.message || String(error));
  }
}

function setupDropZone(type) {
  const zone = document.getElementById(`${type}-dropzone`);
  if (!zone) {
    return;
  }
  const picker = zone.querySelector("input[type='file']");
  if (!picker) {
    return;
  }
  if (picker && ACCEPT_MAP[type]) {
    picker.setAttribute("accept", ACCEPT_MAP[type].join(","));
  }

  const handleFiles = (files) => {
    Array.from(files).forEach((file) => uploadFile(type, file));
  };

  zone.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    picker.click();
  });

  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("is-dragover");
  });

  ["dragleave", "dragend"].forEach((name) => {
    zone.addEventListener(name, () => zone.classList.remove("is-dragover"));
  });

  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("is-dragover");
    handleFiles(event.dataTransfer.files);
  });

  picker.addEventListener("change", () => {
    handleFiles(picker.files);
    picker.value = "";
  });
}

setupDropZone("pdf");
setupDropZone("md");

function buildCrawlConfig() {
  const crawl = {};
  const depth = document.getElementById("crawl-depth").value;
  const pages = document.getElementById("crawl-pages").value;
  const rate = document.getElementById("rate-limit").value;
  const sameDomain = parseBoolean(document.getElementById("same-domain").value);
  const allowSubdomains = parseBoolean(document.getElementById("allow-subdomains").value);
  const includePaths = parseCsv(document.getElementById("include-paths").value);
  const excludePaths = parseCsv(document.getElementById("exclude-paths").value);

  if (depth) crawl.max_depth = Number(depth);
  if (pages) crawl.max_pages = Number(pages);
  if (rate) crawl.rate_limit_per_sec = Number(rate);
  if (sameDomain !== undefined) crawl.same_domain_only = sameDomain;
  if (allowSubdomains !== undefined) crawl.allow_subdomains = allowSubdomains;
  if (includePaths.length) crawl.include_paths = includePaths;
  if (excludePaths.length) crawl.exclude_paths = excludePaths;

  return Object.keys(crawl).length ? crawl : undefined;
}

function buildIngestPayload() {
  const urls = parseList(document.getElementById("urls-input").value);
  const payload = {};
  if (uploadState.pdf.length) payload.pdf_paths = uploadState.pdf.map((item) => item.path);
  if (uploadState.md.length) payload.md_paths = uploadState.md.map((item) => item.path);
  if (urls.length) payload.urls = urls;
  const crawl = buildCrawlConfig();
  if (crawl) payload.crawl = crawl;
  return payload;
}

document.getElementById("api-key-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.apiKey = apiKeyInput.value.trim();
  if (state.apiKey) {
    localStorage.setItem("good_rag_api_key", state.apiKey);
    setOutput("已儲存 API Key", { masked: `${state.apiKey.slice(0, 3)}***` });
  } else {
    localStorage.removeItem("good_rag_api_key");
    setOutput("API Key 已清除", {});
  }
});

document.getElementById("clear-api-key").addEventListener("click", () => {
  apiKeyInput.value = "";
  state.apiKey = "";
  localStorage.removeItem("good_rag_api_key");
  setOutput("API Key 已清除", {});
});

document.getElementById("health-check").addEventListener("click", async () => {
  try {
    const data = await apiFetch("/status/health");
    setOutput("健康檢查結果", data);
  } catch (error) {
    setOutput("健康檢查失敗", error.message || String(error));
  }
});

document.getElementById("list-sources").addEventListener("click", async () => {
  try {
    const data = await apiFetch("/sources");
    setOutput("資料來源", data);
  } catch (error) {
    setOutput("來源查詢失敗", error.message || String(error));
  }
});

document.getElementById("random-uuid").addEventListener("click", async () => {
  try {
    const data = await apiFetch("/status/uuid");
    setOutput("隨機 UUID", data);
  } catch (error) {
    setOutput("取得 UUID 失敗", error.message || String(error));
  }
});

document.getElementById("query-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    q: document.getElementById("query-input").value.trim(),
  };
  const topK = document.getElementById("top-k-input").value;
  const domain = parseCsv(document.getElementById("domain-input").value);
  const version = document.getElementById("version-input").value.trim();
  if (topK) payload.top_k = Number(topK);
  if (domain.length) payload.domain_filter = domain;
  if (version) payload.version = version;

  try {
    const data = await apiFetch("/query", { method: "POST", body: payload });
    setOutput("查詢結果", data);
  } catch (error) {
    setOutput("查詢失敗", error.message || String(error));
  }
});

const ingestForm = document.getElementById("ingest-form");
const syncButton = document.getElementById("sync-button");

async function submitIngest(isSync = false) {
  const payload = buildIngestPayload();
  if (!Object.keys(payload).length) {
    setOutput("匯入失敗", "請至少提供一個檔案或 URL");
    return;
  }
  try {
    const endpoint = isSync ? "/sync" : "/ingest";
    const data = await apiFetch(endpoint, { method: "POST", body: payload });
    setOutput(isSync ? "同步匯入已提交" : "匯入工作已提交", data);
    if (data.job_id) {
      document.getElementById("job-id-input").value = data.job_id;
    }
  } catch (error) {
    setOutput("匯入提交失敗", error.message || String(error));
  }
}

ingestForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitIngest(false);
});

syncButton.addEventListener("click", () => submitIngest(true));

document.getElementById("job-status-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const jobId = document.getElementById("job-id-input").value.trim();
  if (!jobId) {
    setOutput("查詢失敗", "請輸入 Job ID");
    return;
  }
  try {
    const data = await apiFetch(`/ingest/${encodeURIComponent(jobId)}`);
    setOutput("匯入狀態", data);
  } catch (error) {
    setOutput("匯入狀態查詢失敗", error.message || String(error));
  }
});

setOutput("介面已載入", "請透過左側操作按鈕呼叫 API。");
