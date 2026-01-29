# Antigravity Migration Prompt

請複製以下 Prompt 並貼上到新電腦的 Antigravity，以快速還原你的開發環境設定。

***

你好，請協助我設定這台電腦的 Antigravity 環境，使其與我的主要開發機一致。請依序執行以下 5 個步驟：

### 1. 設定全域記憶 (User Global Memory)
請將以下規則永久加入你的全域記憶中，確保我們的溝通風格一致：

<MEMORY[user_global]>
#Rules
永遠用繁體中文回覆我
寫文件都用繁體中文
用繁體中文思考
我作業系統環境係macOS
</MEMORY[user_global]>

### 2. 同步與還原檔案
請確認我已經 Clone 了專案儲存庫。如果還沒，請隨時提醒我。
接著，請檢查專案中是否包含以下設定檔，並將它們應用到你的 `.agent` 或相關目錄中：

- **Skills**: 請讀取 `available_skills.md` (或 `available_skills_zh.md`) 並確認你已認知這些技能。
- **Workflows**: 請確認 `.agent/workflows/git-commit.md` 存在並可被呼叫。

### 3. 設定 MCP Servers
請協助我安裝與設定以下 MCP Servers：

1.  **Notion MCP**:
    *   檢查是否已安裝 `notion-mcp-server`。
    *   如果未安裝，請指導我進行安裝。

2.  **NotebookLM MCP**:
    *   專案根目錄下有一個 `notebooklm_config.sample.json`。
    *   請指導我使用該範本來設定 NotebookLM MCPServer。
    *   請提醒我需要從瀏覽器取得 `_Secure-1PSID` (Session ID) 並填入設定檔中。

### 4. 安裝 Python 套件
請讀取專案根目錄下的 `requirements.txt`，並確保環境中已安裝以下關鍵套件：
- `flask`
- `openai-whisper`
- `opencc-python-reimplemented`
- `mlx-whisper`

### 5. 驗證
設定完成後，請簡單回報你的狀態，並準備好開始工作。

***
