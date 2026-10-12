# Raspberry Pi 5 ↔ Mac 掃碼 POC

三個元件：React 前端、樹莓派 FastAPI、Mac FastAPI。樹莓派先寫入自己的 SQLite，再透過 HTTP 同步至 Mac SQLite。Mac 寫入並回應後才標記已同步。相同 ID 的重試不重複新增；相同 ID 搭配不同內容回傳 409。掃同一條碼兩次（不同 ID）會保留兩笔。

## 1. 在 Mac 啟動

需要 Python 3.11+；前端建置使用 Node.js 22.12+（建議 Node 24 LTS）。每個後端只能啟動一個 worker。

終端機 A：
```bash
cd ~/Desktop/mes
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp -n .env.example .env
bash start.sh
```

終端機 B：
```bash
cd ~/Desktop/raspberrypi/frontend
npm ci
npm run build
cd ../backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp -n .env.example .env
bash start.sh
```

瀏覽器開 http://localhost:8001 。輸入 `001234` 並送出，應顯示已存本機，接著已同步。

Mac 已保存紀錄：http://localhost:8000/api/scans 。API 操作頁：http://localhost:8000/docs 。兩個資料庫分別在 `mes/data/scans.db` 與 `raspberrypi/backend/data/scans.db`。

前端開發模式：保持兩個後端執行，再於 frontend 執行 `npm run dev`，開 http://localhost:5173 。修改後若要由 8001 提供新版頁面，重新 build；第一次產生 dist 後需重啟樹莓派 backend。

## 2. GitHub 搬到樹莓派

建議把 `~/Desktop/raspberrypi` 當成一個 repo，包含 frontend、backend 及這份 README。Mac 的 mes 可用另一個 repo。尚未替你建立或上傳 GitHub repo。

`.gitignore` 排除 `.env`、資料庫、.venv、node_modules 和 dist；套件 lock 檔應一起提交。不要把 Mac 的 .venv 或 node_modules 複製到 ARM 樹莓派。

先在 Mac 的 Wi-Fi 網路設定查看 IP，例如 `192.168.1.20`，並保持 Mac 清醒、服務運作。後端監聽 0.0.0.0；若 macOS 提示網路連線權限，允許此服務的區域網路連線。

透過 Raspberry Pi Connect 開啟 **Remote shell**，以下命令在樹莓派執行：
```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip tmux
# 將下一行 URL 改為你自己建立的 GitHub repo
git clone <你的-repo-URL> ~/raspberrypi
cd ~/raspberrypi/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp -n .env.example .env
nano .env
```

把 `.env` 的 `MAC_API_URL` 改成 `http://192.168.1.20:8000`（填你的 Mac IP）；`DEVICE_ID=pi5-01` 可保留。不要填 localhost，那會指向樹莓派自己。相對 DB_PATH 以 backend 目錄為基準。

在樹莓派先驗證連線：
```bash
curl --fail http://192.168.1.20:8000/api/health
hostname -I
```
應收到包含 `service: mes` 與 `status: ok` 的 JSON。記下 `hostname -I` 顯示的 Wi-Fi IP。

### 建置前端

先在樹莓派執行 `node --version` 與 `npm --version`。需要 Node 22.12+，建議使用 Node 24 LTS 的官方 Linux ARM64 發行版或你的 Node 版本管理工具。如果系統 Node 太舊，請先升級後再安裝前端。

```bash
cd ~/raspberrypi/frontend
npm ci
npm run build
```

若不想在樹莓派安裝 Node，可在 Mac build 後，將整個 frontend/dist 目錄另行複製到樹莓派相同位置；執行編譯好的頁面只需要 Python backend。

### 啟動並保持服務運作

```bash
tmux new -s scan-poc
cd ~/raspberrypi/backend
bash start.sh
```

按 Ctrl+B，放開後按 D，會離開 tmux 但保留服務。下次 `tmux attach -t scan-poc` 回到服務畫面，Ctrl+C 停止。tmux 不會在樹莓派重開機後自動啟動；要常駐開機服務可依 backend/README.md 安裝 systemd。

在 **Mac 瀏覽器** 開 `http://<樹莓派-IP>:8001`，不用接螢幕。在 macOS 出現瀏覽器的「區域網路」權限提示時，允許存取。

Connect 提供遠端 shell，並不自動公開本 POC 網址；Mac 瀏覽器與樹莓派仍須能透過區域網路互通。

## 3. 驗收

1. 正常：從樹莓派網頁輸入 `001234`，在 Mac `/api/scans` 找到同 ID、同條碼；前導零保留。
2. 離線：停止 Mac 後端，輸入三筆；樹莓派仍保存，待同步數增加。當前顯示的錯誤會在下次成功同步時清除。
3. 恢復：重啟 Mac 後端；應自動補送，待同步變零。
4. 持久化：Mac 停止時输入資料，再停止、重啟樹莓派後端；紀錄與待同步仍在。
5. 防重複：相同 ID 的 API 請求重送只保留一筆；同條碼、不同 ID 是兩筆事件。
6. 瀏覽器到樹莓派中斷：顯示「尚未確認保存成功」；恢復後按「重試這筆」沿用 ID。頁面也會保存這筆未確認輸入以便重載後重試。它不是完整離線前端，樹莓派服務不可達時不接受連續新增。

Mac 自動整合測試（使用暫存資料庫，不影響實際資料）：
```bash
cd ~/Desktop/raspberrypi/backend
MES_SOURCE="$HOME/Desktop/mes" .venv/bin/python test_integration.py
```

## 4. 掃描槍與無螢幕使用

目前支援 USB HID 鍵盤模式＋結尾 Enter。**掃描槍需接在正在操作網頁的電腦上**，且輸入框要有焦點。現在用 Mac 瀏覽器操作，掃描槍就接 Mac。

若未來要把掃描槍接到沒有螢幕、沒有本地瀏覽器的樹莓派，需另加背景 HID/串列輸入程式；Connect 的遠端 shell 不會把樹莓派 USB 掃碼自動送到 Mac 網頁。這不屬於目前的瀏覽器輸入 POC。

## 5. 限制與排查

- 範圍：可信任區域網路、少量測試資料、單向同步、不可修改紀錄；HTTP 無登入，不應公開到網際網路。
- Mac 必須保持清醒；Wi-Fi 訪客模式/AP isolation、防火牆、VPN、IP 改變都可能影響連線。先測健康檢查，再測網頁。
- Mac URL 經 `.env` 設定；修改後重啟樹莓派 backend。PORT 可用 `PORT=8002 bash start.sh` 覆寫，需同步調整相關 URL。
- 每 5 秒補送一次，新增資料也會喚醒同步。請求逾時為 3 秒。錯誤保留且重試，409 等內容衝突需人工檢查。
- SQLite 可承受程序重啟，但不是 SD 卡損壞/突然斷電的完整備援方案。不要在線直接搬移 DB 與 WAL；POC 備份時先停止服務再複製 data 目錄。
- 前端最多顯示最近 100 筆；API 可用 `?limit=1000`，數量統計涵蓋所有紀錄。
- POC 已在 Mac 以兩個服務模擬流程；實際 Wi-Fi、樹莓派硬體和掃描槍仍需部署後驗收。

參考：[Raspberry Pi Connect](https://www.raspberrypi.com/documentation/services/connect.html)、[Vite](https://vite.dev/guide/)、[SQLite 跨網路存取](https://www.sqlite.org/useovernet.html)。
