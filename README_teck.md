# good_RAG 後端技術白皮書（v1）

本文件用可落地、可擴充的角度，完整拆解本專案後端如何處理資料與查詢，讓一個「可運作的範例骨架」逐步演進為「工程可維護、效能優秀的 RAG 系統」。內容包含：當前實作、背後思維、取捨、已知缺點與下一步 Roadmap（含決策邏輯）。

## 目標與設計哲學

- 最小可行骨架（MVP）：先讓「匯入→索引→檢索→回覆」端到端可用，再逐步替換模組以提升品質與效能。
- 組件鬆耦合：以 REST/任務佇列邊界把模塊切開，便於替換（OpenSearch、嵌入、LLM 等）。
- 可觀測性優先：每一步都能輸出可檢視的中介資料（查詢體、計時、文件計數）。
- 預留最佳化入扣：chunking、向量索引、重排、融合、LLM 提示工程皆可逐段升級。

## 系統全貌

- API 層：FastAPI（:8000），路由於 `app/api/main.py:41`，並提供 UI 靜態頁 `/ui/`。健康檢查整合 Celery、OpenSearch、Ollama。
- 非同步任務：Celery Worker（Redis broker/backend）。匯入流程 `worker.ingest` 定義於 `app/worker/tasks.py:23`。
- 搜尋儲存：OpenSearch 2.13（dense_vector + cosine）。索引 schema 由 `app/search/opensearch_client.py:73` 以模型維度偵測結果動態建立。
- 向量服務：Ollama（`nomic-embed-text:v1.5`），封裝於 `app/search/embedding.py:16`。
- 回覆生成：若 `.env` 提供 `GEMINI_API_KEY`，於 `app/search/generation.py:1` 使用 `google-genai`（預設 `gemini-2.5-flash`）；否則退回片段摘要。

## 匯入（Ingestion）

- 檔案/來源
  - 上傳：`POST /upload`（`app/api/main.py:116`）接收 PDF/Markdown，多檔儲存至共享目錄 `/data/uploads`（`UPLOAD_DIR` 可調整）。
  - Markdown：`app/ingestors/md.py` 以最小規則讀取，保留原文並去除尾隨空白。
  - PDF：`app/ingestors/pdf.py:14` 使用 `pypdf` 擷取文字；解析失敗不終止流程、僅記錄 warning。
  - 網頁：`app/ingestors/web.py:47` 以 requests 下載 + BeautifulSoup 取正文（剔除 script/style/noscript），暫不做 JS 渲染與 robots 規則。

- 規劃與節流
  - `CrawlConfig`：`max_depth`、`max_pages`、`same_domain_only`、`allow_subdomains`、`rate_limit_per_sec`、include/exclude paths。
  - 目前 `plan_crawl` 僅 URL 正規化與截斷，明確保留 BFS 擴展空間。

- 切塊（Chunking）
  - `app/preproc/chunker.py:29` 使用 whitespace token window（`target_size=750`、`overlap=80`）。
  - 每個 chunk 具 `metadata`（`doc_id`、`source`、`url`、`chunk_index`、`token_start/end`），便於追蹤與重建原文脈絡。

- 嵌入（Embedding）
  - `app/search/embedding.py:16` 以 Ollama embeddings API 一段一請求生成向量；失敗回空向量、後續標記 skipped。

- 索引（Indexing）
  - `app/search/opensearch_client.py:104` 使用 Bulk API 寫入：`content`、`content_vector`、`source`、`url`、`version`、`h_path`、`doc_key`、`content_hash`、`last_seen_at`。
  - 向量欄位 `dense_vector` + `cosine`，維度由 `_detect_embedding_dims` 透過 Ollama 自動偵測。

- 回報（observability）
  - 匯入任務返回 `chunk_count`、`indexed_chunks`、`skipped_chunks`、`fetched_pages`、`crawl_plan`、`sources` 等，利於 UI 與除錯。

## 查詢（Retrieval + Fusion + Generation）

- 流程（`app/search/service.py:79`）
  1. 產生查詢向量（Ollama），計時 `embedding_ms`。
  2. BM25 檢索（OpenSearch `match`），取 `bm25_top_n` 候選。
  3. API 端以 cosine re-rank（`_vector_ranking`），記錄 `rerank_ms`。
  4. RRF 融合（`app/search/hybrid.py`），取前 `query_top_k` 作為 citations。
  5. 有金鑰則以 Gemini 生成繁中摘要，否則回傳片段摘要；`diagnostics` 回傳查詢體與各階段耗時。

- 為何先採「API 端 re-rank」而非 OpenSearch `script_score`
  - 2.13 + dense_vector 在不同部署對 painless/KNN docvalues 細節可能不一致；骨架優先可控性與可除錯性。
  - 後續可自然替換為：KNN/HNSW 原生查詢、hybrid（text + knn）、或外部向量庫（FAISS/Qdrant）。
  - 優點：可靠、能加入應用層權重（source/version/time）；代價：多一次往返與 API 端 CPU 開銷。

- 生成（LLM）
  - `app/search/generation.py` 組合 prompt（多來源 snippets + 明確指示：繁中、條列、[Source N] 引用）。
  - 模型預設 `gemini-2.5-flash`（`.env` 可調 `GEMINI_MODEL`）。

## 資料模型與索引設計

- 主鍵 `doc_key = {doc_id}::{chunk_index}`，保障 chunk 層級去重/更新。
- `content_hash` 用於內容變化偵測（支援日後 upsert 與 TTL 策略）。
- `source`/`url`/`version`/`h_path` 便於多來源串接與前端呈現（例如版本篩選、語系切換）。

## 效能與品質思維

- Chunking 選擇：MVP 以 token 視窗，易調參與推理；後續可加入段落/標點對齊、標題樹切塊、語義切塊（embed similarity split）。
- 候選數量：BM25 提召回、向量提語義；過少影響融合，過多增加 re-rank 時間。
- RRF 融合：以 `k` 平滑抑制單一排序偏差，未來可導入學習式融合。
- LLM 生成：採來源片段驅動，未來可加入長度控制、拒答規則、JSON 結構化輸出與引用檢核（Groundedness）。

## 安全、設定、觀測

- 安全：
  - `API_KEY`（可選）為 Header 驗證；
  - 上傳僅允許 `.pdf/.md/.markdown/.mdown/.txt`，存放隔離目錄並支援 API 刪除。
- 設定（`app/config.py`）：
  - OpenSearch/Ollama/Redis URL、嵌入模型、索引名、Crawl 預設、HTTP timeout、RRF 與 Top-K、Gemini 金鑰與模型、上傳目錄。
  - `docker-compose.yml` 已把 `GEMINI_API_KEY`/`GEMINI_MODEL` 注入容器。
- 觀測：
  - `/status/health` 實測 OpenSearch、Ollama；`diagnostics` 回傳查詢體與計時；匯入結果含統計與 skipped；容器日誌 `docker compose logs -f api worker`。

## 現況限制與已知缺點

- 爬蟲僅單頁擷取；未處理 robots/站內 BFS/JS 渲染。
- 切塊為 whitespace 視窗；未做語義邊界/父子兄弟段擴展。
- re-rank 在 API 端；尚未啟用 KNN 原生混合查詢。
- 去重/更新策略尚未實作（已保留 `content_hash/last_seen_at` 鉤子）。
- 離線評估與 A/B 測試工具尚未完成（`app/eval/` 為占位）。

## Roadmap（含決策邏輯）

1. 內容取得強化（Why：原始資料品質）
   - 站內 BFS + robots.txt；Sitemap 導入；增量抓取（ETag/Last-Modified）。
   - JS 渲染（Playwright）對白名單網域開啟以控成本。
2. 正規化與清洗（Why：降低噪音）
   - Markdown 標題樹導出 `h_path`；表格/程式碼語義處理；網頁 boilerplate 移除。
3. 切塊升級（Why：命中品質）
   - 段落對齊、語義切塊；parent + siblings context 寫回索引，查詢端可直接組裝脈絡。
4. 向量索引與混合查詢（Why：更快更準）
   - 啟用 KNN/HNSW、hybrid（text + knn）；向量批嵌並行；必要時引入 GPU 向量庫。
5. 排序學習與融合（Why：超越 RRF）
   - 蒐集互動訊號，採 LTR/LambdaMART；加入 source/version/time 權重並回傳貢獻度。
6. 生成強化（Why：更穩定）
   - Prompt 模板化、多模型策略、JSON 結構化輸出、引用檢核。
7. 可觀測性與評估（Why：可量化改進）
   - Recall/MRR/nDCG 離線評估；線上延遲與命中統計；實驗框架與報表。
8. 同步與生命週期（Why：可維運）
   - 以 `content_hash` 做 upsert、過期清理、版本策略；Scheduler 管理全量/增量。

## 擴充指引（面向專業 RAG 實作）

- 模型替換：
  - 嵌入：擴充 `embedding_client.embed`（建議加入批次/平行介面）。
  - 生成：在 `app/search/generation.py` 引入多路策略（OpenAI/Claude/Gemini）。
- 多資料源/跨索引：
  - 以 `source/version` 作過濾與權重；或跨索引檢索後在應用層融合（或 OpenSearch cross-cluster）。
- 規模化：
  - 啟用 KNN/HNSW + PQ；批嵌入；任務分片與多 worker；將 re-rank/融合遷至 search 層。

## 總結

本專案以「潔淨、易除錯、可演進」為核心，把資料路徑與責任邊界劃分清楚：資料取得 → 切塊 → 向量化 → 索引 → 檢索融合 → 生成。現況已能支援拖拽上傳、URL 匯入、向量索引與 LLM 摘要；下一步聚焦於「更好的切塊與查詢計畫」、「原生 KNN 混合」、「結構化生成與評估」，在短期內帶來穩健品質提升，同時保留長期擴展彈性。














# good_RAG 後端技術小白課本（v1）

一看就知道整個系統（FastAPI + Celery + OpenSearch + Ollama + Gemini）是怎麼連在一起運作的。

---

## 🧩 一、整體架構：誰做什麼？

| 模組                          | 角色                              | 程式位置                                                        |
| --------------------------- | ------------------------------- | ----------------------------------------------------------- |
| 🧠 **FastAPI (API層)**       | 提供 HTTP 端點：上傳、匯入、查詢、健康檢查、UI 靜態頁 | `app/api/main.py`                                           |
| ⚙️ **Celery Worker (背景工人)** | 處理重工作業（例如匯入文件、斷詞、嵌入、索引）         | `app/worker/tasks.py` / `app/worker/app.py`                 |
| 🔍 **Search Engine (檢索層)**  | 處理混合搜尋（BM25 + 向量重排 + RRF融合）     | `app/search/service.py`、`app/search/hybrid.py`              |
| 🧩 **Embedding + Indexing** | 用 Ollama 建立向量嵌入，存進 OpenSearch   | `app/search/embedding.py`、`app/search/opensearch_client.py` |
| 🤖 **LLM Generation (選用)**  | 用 Gemini 模型生成最終答案               | `app/search/generation.py`                                  |
| ⚙️ **Config 設定中心**          | 管理 `.env`、環境變數                  | `app/config.py`                                             |

💡 簡單說：

```
使用者 → FastAPI (API) → Redis → Celery Worker → Ollama + OpenSearch
                                       ↓
                                   Gemini 生成答案
```

---

## 🐳 二、Docker 架構：怎麼包、怎麼跑？

這專案用 `docker-compose.yml` 一次啟動所有服務：

| 容器                | 用途                                 | 重要設定                |
| ----------------- | ---------------------------------- | ------------------- |
| 🧠 **api**        | FastAPI 主服務（提供 HTTP API）           | 埠 8000              |
| 🧑‍🏭 **worker**  | Celery 背景工人（執行 heavy 任務）           | 同樣使用 api 的映像，只改啟動命令 |
| 🔍 **opensearch** | 文件索引與檢索引擎                          | 埠 9200、停用安全插件       |
| ⚙️ **redis**      | 任務佇列與結果儲存（Celery 的 broker/backend） | 埠 6380（主機對應）        |
| 🧩 **ollama**     | 向量嵌入服務（nomic-embed-text 模型）        | 埠 11434             |

📁 Volume：

* `/data/uploads`：共用上傳檔案目錄
* `ollama`：儲存 Ollama 模型資料

🔧 關鍵環境變數：

```
OS_URL=http://opensearch:9200
OLLAMA_URL=http://ollama:11434
OLLAMA_EMBED_MODEL=nomic-embed-text:v1.5
INDEX_NAME=docs_chunks_v1
GEMINI_API_KEY=...
```

---

## 📥 三、資料匯入（Ingestion Pipeline）

> 一句話：**把文件變成可搜尋的「斷片 + 向量 + 索引」資料。**

### 1️⃣ 觸發方式

API：

* `POST /ingest` → 非同步，交給 Celery
* `POST /sync` → 同步執行（直接在 API 端跑）
  → 對應程式：`app/api/main.py`、`app/worker/tasks.py`

### 2️⃣ 讀資料

* `pdf.py` → 用 `pypdf` 擷取文字
* `md.py` → 處理 Markdown
* `web.py` → 下載網頁、清理 HTML、取正文

### 3️⃣ 切塊（Chunking）

* 把長文字切成固定長度（預設 750 tokens、重疊 80）
* 每個 chunk 都加 metadata（來源、頁數、位置）
  → `app/preproc/chunker.py`

### 4️⃣ 向量嵌入（Embedding）

* 呼叫 Ollama embedding API 把文字轉成向量
* 模型：`OLLAMA_EMBED_MODEL` 指定
  → `app/search/embedding.py`

### 5️⃣ 寫入索引（Indexing）

* 用 OpenSearch 建立索引（自動偵測向量維度）
* 批次寫入（Bulk API）
  → `app/search/opensearch_client.py`

📤 最後會回傳：

* 擷取頁面數
* 成功索引數
* 跳過數
  → `app/worker/tasks.py`

---

## 🔍 四、查詢與生成流程（Retrieval + Generation）

> 查詢是「檢索」+「融合」+「生成」三步走。

### 1️⃣ 查詢入口

`POST /query`
→ `app/api/main.py`、`app/search/service.py`

### 2️⃣ 檢索流程

1. 對查詢語句做向量嵌入
2. 用 OpenSearch 的 **BM25** 拿文本候選
3. 用 cosine similarity 對候選重排（純 Python）
4. 用 **RRF (Reciprocal Rank Fusion)** 融合排名
5. 整理 citations（來源）

→ `app/search/hybrid.py`

### 3️⃣ 生成答案（選用）

* 若設定 `GEMINI_API_KEY` → 用 Gemini 生成繁中摘要
* 沒有則回 fallback：取前幾筆片段摘要
  → `app/search/generation.py`

---

## 🧩 五、整體資料流（超簡化版）

```
📄 PDF / MD / URL
     │
     ▼
 [FastAPI]
     │ 送出 Celery 任務
     ▼
 [Celery Worker]
     ├─ 擷取文字 (ingestors)
     ├─ 切塊 (preproc)
     ├─ 嵌入 (Ollama)
     └─ 索引 (OpenSearch)
     ↓
   [OpenSearch 儲存向量]

查詢時：
User Query → FastAPI → 檢索融合 → Gemini 生成回答
```

---

## 🧠 六、為什麼這樣設計？

| 模組             | 原因                |
| -------------- | ----------------- |
| FastAPI        | 提供高效 API 與非同步查詢   |
| Celery         | 避免重任務卡住主程式        |
| Redis          | 任務佇列（broker）與結果存放 |
| OpenSearch     | 快速全文 + 向量檢索       |
| Ollama         | 本地嵌入生成            |
| Gemini         | 答案生成（LLM）         |
| Docker Compose | 一鍵啟動整套系統          |

---

## ✅ 七、一句話總結

> 這是一套完整的 **RAG（Retrieval-Augmented Generation）後端系統**，
> 以 FastAPI 為門面、Celery 為工人、OpenSearch 為資料庫、Ollama 提供語義向量、
> 可選擇用 Gemini 做最終生成。

---

要不要我幫你畫一張圖，把整個架構（FastAPI + Celery + Redis + Ollama + OpenSearch + Gemini）一眼看懂？
我可以畫成像工程架構圖那樣的簡圖。
