# good_RAG

一個以 API 文件為核心的 RAG（Retrieval-Augmented Generation）系統參考實作。
此專案依據對應的產品需求文件設計，提供端到端骨架：可匯入 PDF、Markdown 與靜態網站，
產生混合式（BM25 + 稠密向量）檢索查詢，並透過 FastAPI 暴露工作流程，背景任務由 Celery 驅動。

## 功能

- 使用 **Docker Compose** 一次啟動 OpenSearch、Redis、Ollama、FastAPI 與 Celery。
- **可設定的匯入模型**，支援檔案路徑與爬蟲選項。
- **可擴充的處理骨架**：PDF / Markdown / 網頁，預留清楚的擴充點。
- **混合檢索腳手架**：內含 RRF（Reciprocal Rank Fusion）工具與 OpenSearch 索引啟動邏輯，
  可從 Ollama 自動偵測嵌入向量維度。
- **離線評估骨架**：支援 Recall / MRR / nDCG 等評估指標的基礎結構。

## 本地啟動（完整流程）

以下提供兩種在本地啟動方式：
- 方案 A：使用 Docker Compose（推薦，最簡單）
- 方案 B：原生執行 API 與 Worker（相依服務以本機或 Docker 提供）

在開始前，請先複製環境設定：

1) 複製環境檔
- 從根目錄複製：
  ```bash
  cp .env.example .env
  ```
- 若之後採原生執行，請把 `.env` 內的連線改成本機位址，例如：
  - `OS_URL=http://localhost:9200`
  - `REDIS_URL=redis://localhost:6379/0`
  - `OLLAMA_URL=http://localhost:11434`
  - 若要整合 Gemini 產生式模型，可額外設定 `GEMINI_API_KEY=<你的金鑰>`（可於 Google AI Studio 取得）。
  - 檔案上傳共享資料夾預設為 `/data/uploads`，可透過 `UPLOAD_DIR` 調整。
- Docker Compose 會自動讀取根目錄 `.env`，因此只要在該檔設定 `GEMINI_API_KEY`（以及可選的 `GEMINI_MODEL`），容器啟動時便能安全載入金鑰。

### 方案 A：Docker Compose（推薦）

前置需求：
- 已安裝 Docker Desktop（或相容的 Docker 環境）。
- 建議至少 6GB RAM 可用（OpenSearch 預設配置 2GB JVM）。

步驟：
1. 啟動整套服務（第一次會自動建置映像）
   ```bash
   docker compose up --build -d
   ```
2. 下載 Ollama 的嵌入模型（供向量維度偵測與後續嵌入用）
   ```bash
   docker compose exec ollama ollama pull nomic-embed-text:v1.5
   ```
3. 驗證服務健康狀態
   - 開啟 API Swagger 文件：`http://localhost:8000/docs`
   - 以 curl 檢查健康度（如未設定 API 金鑰，可省略 Header）：
     ```bash
     curl -s http://localhost:8000/status/health | jq
     ```
4. 測試查詢（混合檢索樣板，回傳示例結構）
   ```bash
   curl -s -X POST http://localhost:8000/query \
     -H 'Content-Type: application/json' \
     -d '{"q":"What is hybrid retrieval?"}' | jq
   ```
5. 觸發匯入（示例：以 URL 規劃爬蟲前沿，不會真的抓網頁）
   ```bash
   curl -s -X POST http://localhost:8000/ingest \
     -H 'Content-Type: application/json' \
     -d '{"urls":["https://example.com/docs"],"crawl":{"max_pages":10}}' | jq
   # 取得 job_id 後查詢狀態
   curl -s http://localhost:8000/ingest/<job_id> | jq
   ```
6. 若要匯入本機檔案（Markdown/PDF）
   - 由於容器無法直接讀取主機檔案，請將資料夾掛載進 `api` 與 `worker` 容器。
   - 建議新增 `docker-compose.override.yml`（不需修改原檔）：
     ```yaml
     services:
       api:
         volumes:
           - ./data:/data:ro
       worker:
         volumes:
           - ./data:/data:ro
     ```
   - 將檔案放到本機 `./data`，再以下列路徑呼叫 API：
     ```bash
     curl -s -X POST http://localhost:8000/ingest \
       -H 'Content-Type: application/json' \
       -d '{"md_paths":["/data/sample.md"], "pdf_paths":["/data/spec.pdf"]}' | jq
     ```

常見問題（Docker Compose）：
- 健康檢查顯示 worker 為 unavailable：多等幾秒，或檢查 `docker compose logs worker`。
- OpenSearch 9200 連不到：確認容器有啟動，或調整可用記憶體。
- OpenSearch 2.13 需要安全性初始密碼；Compose 已預設 `OPENSEARCH_INITIAL_ADMIN_PASSWORD=Opensearch!2024`，若自行啟動請提供符合規則的密碼。
- Ollama 模型拉取失敗：重試 `docker compose exec ollama ollama pull nomic-embed-text`。
- 若需從主機連線 Redis，請改用 `redis://localhost:6380/0`（容器內仍是 6379）。

### 方案 B：原生執行（不使用 Docker 啟動 API/Worker）

此方案適合想在本機以 Python 啟動 API 與 Celery Worker，
相依的 OpenSearch / Redis / Ollama 可使用本機安裝或以 Docker 啟動。

前置需求：
- Python 3.11
- OpenSearch（建議用 Docker 執行）
- Redis（本機或 Docker）
- Ollama（本機或 Docker；需 `nomic-embed-text` 模型）

1) 建立虛擬環境並安裝套件
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) 啟動相依服務（擇一）
- 使用 Docker 啟動相依服務（僅 OpenSearch/Redis/Ollama）：
  ```bash
  docker run -d --name opensearch -p 9200:9200 \
    -e discovery.type=single-node -e "OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g" \
    -e plugins.security.disabled=true opensearchproject/opensearch:2.13.0

  docker run -d --name redis -p 6379:6379 redis:7-alpine

  docker run -d --name ollama -p 11434:11434 ollama/ollama:latest
  docker exec -it ollama ollama pull nomic-embed-text
  ```
- 或使用已安裝在本機的服務（自行確保上述連接埠可用）。

3) 設定環境變數（或編輯 `.env`）
- `.env` 主要參數（本機執行建議值）：
  - `OS_URL=http://localhost:9200`
  - `REDIS_URL=redis://localhost:6379/0`
  - `OLLAMA_URL=http://localhost:11434`
  - `OLLAMA_EMBED_MODEL=nomic-embed-text`

4) 啟動 API 服務（於專案根目錄）
```bash
python -m app.api
# 或使用 uvicorn
# uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload
```

5) 啟動 Celery Worker（新開一個終端機分頁）
```bash
celery -A app.worker.app.celery_app worker --loglevel=INFO
```

6) 驗證與測試
- 打開 `http://localhost:8000/docs`，或重複「方案 A」中的 curl 範例。

## 安全性（API 金鑰）

- 若在環境變數中設定了 `API_KEY`，呼叫 API 需帶上 `X-API-Key` Header。
- 例：
  ```bash
  export API_KEY=your-secret
  # 之後呼叫：
  curl -H "X-API-Key: $API_KEY" http://localhost:8000/status/health
  ```
- 若未設定 `API_KEY`，則不需要此 Header（僅限本地開發建議）。

## 常用 API 範例

- 健康檢查：
  ```bash
  curl -s http://localhost:8000/status/health | jq
  ```
- 送出匯入工作：
  ```bash
  curl -s -X POST http://localhost:8000/ingest \
    -H 'Content-Type: application/json' \
    -d '{"urls":["https://example.com/docs"],"crawl":{"max_pages":5}}' | jq
  ```
- 查詢匯入狀態：
  ```bash
  curl -s http://localhost:8000/ingest/<job_id> | jq
  ```
- 上傳檔案（UI 亦會自動呼叫）：
  ```bash
  curl -s -X POST http://localhost:8000/upload \
    -H 'X-API-Key: $API_KEY' \
    -F file=@./docs/spec.pdf | jq
  ```
- 查看 OpenSearch 目前的文件數量：
  ```bash
  curl -s http://localhost:9200/docs_chunks_v1/_count | jq
  ```
- 混合檢索查詢：
  ```bash
  curl -s -X POST http://localhost:8000/query \
    -H 'Content-Type: application/json' \
    -d '{"q":"authentication error codes", "top_k":8}' | jq
  ```

## Web UI 操作

- 以瀏覽器開啟 `http://localhost:8000/ui/`，即可使用單頁式控制台進行健康檢查、查詢與匯入。
- 介面左上角可儲存 `X-API-Key`，若後端啟用了 `API_KEY` 驗證，請先輸入並儲存再操作。
- PDF / Markdown 檔案可直接拖曳或點擊上傳；檔案會儲存在容器的 `/data/uploads` 共享資料夾並自動帶入匯入路徑。
- 匯入表單仍支援多個 URL，並可選擇同步模式（呼叫 `/sync` 端點）。
- 所有結果會顯示在「結果」面板，可直接複製 JSON 內容以利除錯。
- 若設有 `GEMINI_API_KEY`，查詢結果會使用 Gemini `gemini-2.5-flash` 生成摘要；未設定時則回退為片段摘要。

## 專案結構

```
app/
  api/          # FastAPI 路由與應用組裝
  configs/      # 同義詞與爬蟲設定樣板
  eval/         # 離線評估骨架
  ingestors/    # PDF / Markdown / Web 載入器
  preproc/      # 切塊與中繼資料處理工具
  search/       # OpenSearch 用戶端與混合檢索工具
  worker/       # Celery 應用與任務
  ui/           # 前端佔位
```

## 開發說明

- 匯入流程 (`worker.ingest`) 會實際讀取 PDF（使用 `pypdf`）、Markdown 與 URL（透過 `requests` + `beautifulsoup4`），建立切片、呼叫 Ollama 生成嵌入，最後用 OpenSearch Bulk API 寫入 `docs_chunks_v1` 索引。
- 查詢流程會先以 BM25 擷取候選，再以查詢向量與文件向量的餘弦相似度重新排序，並透過 Reciprocal Rank Fusion 融合分數。
- OpenSearch 用戶端維持使用 `requests`，並在啟動時偵測 Ollama 嵌入維度以建立對應的索引 mapping；如需調整欄位或新增 metadata，可修改 `app/search/opensearch_client.py`。
- 查詢結果若偵測到 `GEMINI_API_KEY` 會透過 `app/search/generation.py` 調用 Gemini（預設 `gemini-2.5-flash`）生成摘要；若未提供金鑰則退回片段式摘要。
