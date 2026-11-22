# LinuxCK bốn vai trò

| Máy | Vai trò | Lệnh Compose |
|---|---|---|
| 1 | Master, RabbitMQ, PostgreSQL, FastAPI, dashboard, Telegram | `docker compose --env-file deploy/.env.master -f deploy/master.compose.yml up --build -d` |
| 2 | Binance Spot | `WORKER_ID=worker-2 EXCHANGE=binance docker compose --env-file deploy/.env.worker -p linuxck-binance -f deploy/worker.compose.yml up --build -d` |
| 3 | OKX Spot | `WORKER_ID=worker-3 EXCHANGE=okx docker compose --env-file deploy/.env.worker -p linuxck-okx -f deploy/worker.compose.yml up --build -d` |
| 4 | Bybit Spot | `WORKER_ID=worker-4 EXCHANGE=bybit docker compose --env-file deploy/.env.worker -p linuxck-bybit -f deploy/worker.compose.yml up --build -d` |

Sao chép `deploy/.env.example` vào tệp tên tương ứng và điền mật khẩu riêng. Trong Master, `POSTGRES_DSN` trỏ service `postgres:5432`, `MASTER_ADDRESS` trỏ service `rabbitmq:5672`. Ở Worker, `MASTER_ADDRESS` là URL AMQP qua địa chỉ nội bộ của Máy 1. Đặt `MASTER_BIND` thành địa chỉ Tailscale của Master khi đã có mạng riêng. PostgreSQL chỉ cần mạng Compose nội bộ. Dashboard và AMQP mẫu bind loopback. Cấu hình TLS và phân quyền RabbitMQ theo vhost cho triển khai ngoài môi trường tin cậy.

Compose chỉ cần khi chủ dự án chủ động chạy. Để dừng, dùng cùng lệnh với `stop` thay cho `up --build -d`. Không dùng `down -v` nếu giữ dữ liệu. Ba project Compose có ba volume SQLite độc lập. Cấu hình Beszel Hub tại Master, Beszel Agent trên bốn máy và kết nối qua IP Tailscale khi có hạ tầng. Dashboard đã có heartbeat và tài nguyên của Master. TimeGPT để mở ở phần phân tích Master, chưa có lời gọi API.

## Chạy giới hạn trong một môi trường

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r distributed/requirements.txt
# Cấp POSTGRES_DSN và MASTER_ADDRESS cho hai container thử nghiệm qua biến môi trường.
TELEGRAM_ENABLED=false .venv/bin/python -m uvicorn distributed.master:create_app --factory --host 127.0.0.1 --port 58080
EXCHANGE=binance DATABASE_PATH=worker/trial/distributed/binance.sqlite3 .venv/bin/python -m distributed.node --seconds 315 --flush 8
EXCHANGE=okx DATABASE_PATH=worker/trial/distributed/okx.sqlite3 .venv/bin/python -m distributed.node --seconds 315 --flush 8
EXCHANGE=bybit DATABASE_PATH=worker/trial/distributed/bybit.sqlite3 .venv/bin/python -m distributed.node --seconds 315 --flush 8
.venv/bin/python -m pytest worker/tests distributed/tests -q
```

Chạy các lệnh Worker trong ba terminal nếu muốn chạy song song. PostgreSQL/RabbitMQ integration cần `SIM_POSTGRES_DSN` trỏ database có tên `linuxck_sim` và `SIM_AMQP` trỏ vhost có tên `linuxck-sim`. Test có quyền tắt kết nối vào đúng database thử nghiệm đó để xác minh phục hồi. Live và simulation dùng database/vhost độc lập. Lệnh Worker cũ `python -m worker` vẫn dùng SQLite riêng của thử nghiệm Binance trước.

## Giao thức

- Mỗi bản tin có `version`, `id`, `idempotency_key`, `collection_id`, `worker_id`, `exchange`, `market`, `kind` và `data`. Chỉ chấp nhận Spot / USDT. Giá, khối lượng và phần trăm dùng chuỗi thập phân; mốc thời gian dùng UTC. Timestamp không có ở nguồn là null.
- Cùng transaction SQLite ghi dữ liệu và outbox. RabbitMQ publisher confirm chỉ xác nhận vào broker. Consumer ghi PostgreSQL theo khóa duy nhất, commit, rồi publish receipt cho đúng worker và xác nhận delivery gốc. Worker ghi receipt vào SQLite rồi ACK receipt. Nếu mất receipt, cùng ID được phát lại. Bản tin sai vào `linuxck.v1.ingest.dead`; có thể kiểm tra qua RabbitMQ Management trong hạ tầng được cấp quyền. Sự cố tạm thời giữ delivery để retry.
- Cửa sổ giá lấy mẫu theo thời gian thu thập, đánh tuổi theo timestamp nguồn khi có. Ngưỡng mặc định 90 giây. Giá last và bid/ask là các trường riêng. Số liệu chênh lệch có thể chịu ảnh hưởng của thời điểm lấy mẫu và độ trễ giữa các sàn.
- Telegram mặc định dry-run. Bản ghi report/spread được chống trùng theo symbol, cửa sổ và loại. Cấu hình `TELEGRAM_REPORT_INTERVAL`, `TELEGRAM_SPREAD_THRESHOLD`, `TELEGRAM_COOLDOWN`, `TELEGRAM_SYMBOLS`. Chỉ cấp token, chat ID và bật `TELEGRAM_ENABLED` khi người dùng đã cho phép.
