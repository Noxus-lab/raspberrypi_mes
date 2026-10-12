# 樹莓派 Backend

完整部署與驗收見 ../README.md。所有 DB 路徑以 backend 為基準。單一 uvicorn worker；每筆輸入先提交 SQLite，再由背景程序送至 Mac。

## 可選：開機自動啟動

先完成一般部署驗收。建立 `/etc/systemd/system/scan-poc.service`，把 `YOUR_USER` 換成樹莓派實際帳號（用 `whoami` 查），路徑也要符合實際 clone 位置：

```ini
[Unit]
Description=Scan POC backend and frontend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/raspberrypi/backend
ExecStart=/home/YOUR_USER/raspberrypi/backend/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8001 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

先停止 tmux 裡手動啟動的 backend，避免 port 衝突，再執行：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scan-poc
systemctl status scan-poc
journalctl -u scan-poc -n 50 --no-pager
```
停止：`sudo systemctl stop scan-poc`。更新程式並 build 後：`sudo systemctl restart scan-poc`。
