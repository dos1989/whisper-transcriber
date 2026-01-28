---
description: Git commit and push - 快速提交和推送代碼到 GitHub
---

# Git Commit 工作流

這個工作流幫助你快速提交代碼到 Git 並推送到 GitHub。

## 使用方法

當用戶說 "/git-commit" 或要求 commit git 時，執行以下步驟：

## 步驟

1. **檢查 Git 狀態**
   ```bash
   git status
   ```
   檢查是否有未提交的更改。

2. **查看更改內容**
   ```bash
   git diff --stat
   ```
   ```
   顯示更改的檔案摘要。

3. **下載更新 (Pull)**
   在提交之前，先拉取遠端更新以避免衝突：
   ```bash
   git pull
   ```

4. **添加所有更改**
   // turbo
   ```bash
   git add -A
   ```

5. **提交更改**
   根據更改內容，生成有意義的 commit 訊息：
   - 使用繁體中文或英文（根據用戶偏好）
   - 遵循 Conventional Commits 格式：
     - `feat:` 新功能
     - `fix:` 修復錯誤
     - `docs:` 文檔更新
     - `style:` 樣式調整
     - `refactor:` 重構
     - `chore:` 維護
   
   ```bash
   git commit -m "類型: 訊息描述"
   ```

6. **推送到遠端**
   // turbo
   ```bash
   git push
   ```
   
   如果還沒有設定遠端，先問用戶是否要創建 GitHub repo：
   ```bash
   gh repo create <repo-name> --public --source=. --push
   ```

## 注意事項

- 如果沒有 .gitignore，先建議創建一個
- 如果是首次 commit，使用 `git init` 初始化
- 確保 commit 訊息簡潔但有意義
