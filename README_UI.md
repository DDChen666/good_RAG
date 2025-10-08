# good_RAG 本地 UI 操作說明（localhost:8000/ui）

本文帶你完整理解 UI 的每一個區塊、按鈕與回傳內容，並說明其背後呼叫的 API、參數含義與常見問題。你可以邊開著介面邊對照本文操作。

---

## 介面總覽與前置

- 進入網址：`http://localhost:8000/ui/`
- 是否需要金鑰：
  - 若 `.env` 設定了 `API_KEY`，UI 的所有請求都需要在頁面左側「X-API-Key」先儲存金鑰。
  - 若 `.env` 設定了 `GEMINI_API_KEY`，查詢會使用 Gemini 生成摘要（預設 `gemini-2.5-flash`）。沒設金鑰時仍可查詢，但只回傳片段式摘要。
- 上傳目錄：透過 UI 拖放上傳的 PDF/Markdown 檔案會儲存在容器共享資料夾：`/data/uploads`（可由 `UPLOAD_DIR` 調整）。

---

## 區塊說明與操作

### 1) 認證與基本操作

- X-API-Key（可選）
  - 用途：儲存到瀏覽器的本地儲存，之後 UI 會自動在每次請求加上 `X-API-Key` header。
  - 按鈕：
    -「儲存金鑰」：覆寫或新增金鑰。
    -「清除」：移除已儲存金鑰。

- 健康檢查（/status/health）
  - 顯示 `worker`、`opensearch`、`ollama` 的可用性。例如：`opensearch: yellow` 代表單節點可用（無副本）。

- 列出資料來源（/sources）
  - 範例端點，未來可回傳已接入的資料源清單；目前回空陣列以供 UI 與權限流程測試。

- 取得隨機 UUID（/status/uuid）
  - 用於快速測試 API 呼叫是否正常。

### 2) 混合檢索查詢

- 欄位說明：
  - 查詢內容 `q`（必填）：你的問題或關鍵字。
  - Top K（可選）：限制最終返回的 citation 數量（不填則採預設）。
  - Domain Filter（可選）：以逗號分隔，對 `source` 欄位做條件（例如 `markdown,url`）。
  - 版本標籤（可選）：以 `version` 欄位做條件（例如 `v1.0`）。

- 產出說明：
  - answer：
    - 若設定了 `GEMINI_API_KEY`，會用 Gemini 依據檢索到的片段生成繁中摘要；
    - 否則回傳片段式摘要（擷取前幾筆的簡要句子）。
  - citations：檢索到的片段清單（含 id/title/url/snippet）。
  - diagnostics：效能與除錯資訊（`embedding_ms`、`retrieval_ms`、`rerank_ms`、`total_ms`、查詢體等）。

### 3) 資料匯入

- 檔案上傳（拖放/點擊）
  - PDF 檔案：只接受 `.pdf`。
  - Markdown 檔案：接受 `.md`、`.markdown`、`.mdown`、`.txt`。
  - 上傳後會產生檔案 Pills，顯示原檔名並可點叉叉移除（同時呼叫後端刪除實體檔）。
  - 後端會回傳該檔案在容器內的路徑，UI 會自動把這些路徑填入匯入 payload 的 `pdf_paths`/`md_paths`。

- 網址 URL（每行一筆）
  - 直接在文字框貼入多行網址，匯入時會嘗試擷取靜態 HTML 的正文文字（不含 SPA 動態內容）。

- 爬蟲設定（選填）
  - `最大深度 (max_depth)`：從起始 URL 往外延伸的深度限制。
  - `最大頁數 (max_pages)`：最多處理的頁面數量。
  - `速率限制 (rate_limit_per_sec)`：每秒允許擷取的頁數（簡易節流）。
  - `僅同網域 (same_domain_only)`：是否限制在同網域。
  - `允許子網域 (allow_subdomains)`：是否允許子網域。
  - `Include/Exclude Paths`：以逗號分隔，白名單/黑名單路徑前綴。

- 送出匯入
  -「提交匯入工作」：呼叫 `/ingest` 非同步入庫，回傳 `job_id`。
  -「以同步模式提交」：呼叫 `/sync`，請求會等到流程完成才回應。

- 查詢匯入狀態（/ingest/{job_id}）
  - `state`：`PENDING` / `STARTED` / `SUCCESS` / `FAILURE`。
  - `result`：當 `SUCCESS` 時包含：
    - `sources`：已處理的來源概述。
    - `crawl_plan`：規劃到的網址（不一定都擷取成功）。
    - `fetched_pages`：實際抓取成功的頁面清單。
    - `chunk_count`：切塊數。
    - `indexed_chunks`：成功建立向量並寫入 OpenSearch 的切塊數。
    - `skipped_chunks`：因嵌入失敗等原因跳過的切塊 id。

### 4) 結果面板

- 永遠顯示「最近一次」操作的完整 JSON 回應（可直接複製用於除錯）。
- 若出現錯誤，會把錯誤訊息字串顯示在此處。

---

## UI 與後端端點對照

- 儲存/清除 X-API-Key：只在瀏覽器端儲存，不呼叫 API。
- 健康檢查：`GET /status/health`
- 列出資料來源：`GET /sources`
- 取得隨機 UUID：`GET /status/uuid`
- 上傳檔案：`POST /upload`（multipart；回傳 `path` 供匯入使用）
- 刪除上傳檔：`DELETE /upload/{upload_id}`
- 提交匯入（非同步）：`POST /ingest`
- 提交匯入（同步）：`POST /sync`
- 查詢匯入狀態：`GET /ingest/{job_id}`
- 混合檢索查詢：`POST /query`

Header 規則：若 `.env` 設定了 `API_KEY`，以上端點都需要 `X-API-Key: <你的金鑰>`。

---

## 資料如何被處理

1) PDF/Markdown：
   - 由 UI 上傳到 `/data/uploads` → 匯入時讀取內容 → 以簡單分詞切塊 → 呼叫 Ollama 產生向量 → 寫入 OpenSearch。

2) URL：
   - 先規劃 `crawl_plan` → 對 URL 進行擷取並以 BeautifulSoup 取正文 → 後續步驟與本機檔案相同。

3) 查詢：
   - 以 BM25 取回候選 → 以查詢向量在 API 端進行 cosine re-rank → RRF 融合 →（若有 `GEMINI_API_KEY`）用 Gemini 生成繁中摘要。

---

## 常見疑問與排錯

- 健康檢查 `opensearch: yellow` 正常嗎？
  - 單節點無副本時會是 `yellow`；可直接使用。若需要 `green`，請調整副本數或叢集拓撲。

- 上傳後看不到檔案？
  - 請以 `docker compose exec worker ls /data/uploads` 確認檔案是否已掛載到工作容器（我們已為 `api`/`worker` 兩個服務掛上了同一個 `uploads` volume）。

- 匯入成功但 `indexed_chunks=0`？
  - 多半是嵌入失敗或向量未生成。請檢查：
    - Ollama 是否成功拉到 `nomic-embed-text:v1.5`：`docker compose exec ollama ollama pull nomic-embed-text:v1.5`
    - Worker 日誌：`docker compose logs -f worker`

- 查詢 500 錯誤？
  - 檢查 API 日誌：`docker compose logs -f api`。
  - 確認 OpenSearch 在 9200 可連線、索引存在且有文件：`GET /docs_chunks_v1/_count`。

- Gemini 沒生效？
  - 確認 `.env` 已填 `GEMINI_API_KEY`，且 `docker compose up -d --build` 後容器的環境變數有帶入（Compose 已在 `docker-compose.yml` 中引用 `${GEMINI_API_KEY}`）。

---

## 小技巧

- 需要把結果另存？直接複製「結果面板」的 JSON，或在瀏覽器 DevTools Network 取得原始回應。
- 想要從 CLI 走完整流程：上傳 → 匯入 → 查詢，可以參考 `README.md` 的「常用 API 範例」。

---

## 參考檔案（可快速對照行為）

- UI 靜態資源：`app/ui/static/index.html:1`、`app/ui/static/styles.css:1`、`app/ui/static/app.js:1`
- 上傳與健康檢查 API：`app/api/main.py:112`
- 匯入任務：`app/worker/tasks.py:23`
- 檢索服務（BM25 + 重新排序 + LLM 生成）：`app/search/service.py:10`、`app/search/generation.py:1`

