# MyLife OS

`index.html` 是 App 本体（GitHub Pages 打开）。注意：手机和电脑各自的待办、补货等记录存在各自浏览器里，不会互相同步，只有自动抓取的职位和价格会同步。

## 自动抓职位（第三阶段）
每天 08:00 和 18:00（马来西亚时间）GitHub 自动搜索职位，筛选后写入 `data/jobs_latest.json`，App 从这个文件同步。

**筛选条件**在 `config/jobs.json`：关键词、最低月薪（默认 RM6000）、地点（KL）、最长发布天数（45 天）。薪资未公开的职位默认保留。

### 上线步骤
1. 在 GitHub 新建仓库，把本文件夹全部推上去。要让 App 直接读取职位文件，仓库需要是 **Public**。仓库里不要放任何个人资料、密码或 `.env`。
2. 仓库 → Actions → MyLife OS Daily Automation → Run workflow，command 填 `jobs-verify`。
3. 看日志：每个来源是"找到 N 个职位链接"还是"跳过"。显示 0 个链接，说明 `config/jobs.json` 里的搜索网址格式不对，要改；显示"robots.txt 不允许"，该站就不会被抓。
4. 确认没问题后，再运行一次 command 填 `jobs`，仓库会出现 `data/jobs_latest.json`。之后每天自动更新。
5. 打开网页版：仓库 Settings → Pages → Source 选 Deploy from a branch，Branch 选 `main`，文件夹选 `/ (root)` → Save。几分钟后网址是 `https://你的用户名.github.io/仓库名/`，手机和电脑都用这个网址打开 `index.html`，职位和价格会自动同步，不用填任何网址。
6. 想追踪的商品价格：在 `config/watchlist.json` 加商品网址（name、url、volume_ml、target_price），每天自动记录并同步到 App 的购物页。

### 通知（可选）
在仓库 Settings → Secrets 添加 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`（或邮箱变量），发现新职位时会推送。不加也能正常抓取。

### 规则
- 只读公开页面，抓之前检查 robots.txt，无法确认就不抓；每个请求间隔 2 秒。
- 不登录、不绕过限制。LinkedIn、JobStreet 的使用条款限制自动抓取，所以没有放进来。
- 没有 Supabase 也能运行：数据库默认用 SQLite，职位去重靠 `data/jobs_seen.json`。

## 本地运行
    pip install -r requirements.txt
    python -m backend.main jobs-verify
    python -m backend.main jobs
    pytest

其它模块（购物价格、Gmail、Calendar）说明见 `database/schema.sql` 和各脚本。
