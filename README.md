# LinuxCK

Hệ thống thu thập và so sánh giá Spot từ Binance, OKX và Bybit. Máy 1 chạy RabbitMQ, PostgreSQL và dashboard. Máy 2–4 thu thập độc lập, lưu SQLite và tự gửi lại dữ liệu khi Master kết nối lại.

## Chuẩn bị trên cả bốn máy

Cài Git, Docker Engine và Docker Compose v2 trên Ubuntu Server. Kết nối bốn máy vào cùng mạng Tailscale. Chạy các lệnh dưới đây từ thư mục repo.

```bash
git clone https://github.com/LeSyBach/LinuxCK.git
cd LinuxCK
docker compose version
```

## Máy 1 · Master

Chạy `tailscale ip -4` để lấy IP Tailscale của Máy 1. Tạo `deploy/.env.master` với nội dung sau. Thay `IP_TAILSCALE_MAY_1` và hai mật khẩu mẫu. Có thể chạy `openssl rand -hex 24` hai lần để tạo hai mật khẩu, rồi dùng lại đúng giá trị trong từng URL tương ứng.

```dotenv
MASTER_BIND=IP_TAILSCALE_MAY_1
POSTGRES_PASSWORD=MAT_KHAU_POSTGRES
RABBITMQ_PASSWORD=MAT_KHAU_RABBITMQ
POSTGRES_DSN=postgresql://linuxck:MAT_KHAU_POSTGRES@postgres:5432/linuxck
MASTER_ADDRESS=amqp://linuxck:MAT_KHAU_RABBITMQ@rabbitmq:5672/%2F
TELEGRAM_ENABLED=false
```

```bash
docker compose --env-file deploy/.env.master -f deploy/master.compose.yml up --build -d
docker compose --env-file deploy/.env.master -f deploy/master.compose.yml ps
```

Mở `http://IP_TAILSCALE_MAY_1:8080` từ một máy trong cùng mạng Tailscale. Endpoint `/health` kiểm tra kết nối PostgreSQL.

## Máy 2, 3 và 4 · Worker

Trên **mỗi máy**, tạo `deploy/.env.worker` với IP Tailscale của Máy 1 và cùng mật khẩu RabbitMQ đã đặt trên Master.

```dotenv
MASTER_ADDRESS=amqp://linuxck:MAT_KHAU_RABBITMQ@IP_TAILSCALE_MAY_1:5672/%2F
```

Chạy đúng một lệnh tương ứng với máy.

```bash
# Máy 2 · Binance
WORKER_ID=worker-2 EXCHANGE=binance docker compose --env-file deploy/.env.worker -p linuxck-binance -f deploy/worker.compose.yml up --build -d

# Máy 3 · OKX
WORKER_ID=worker-3 EXCHANGE=okx docker compose --env-file deploy/.env.worker -p linuxck-okx -f deploy/worker.compose.yml up --build -d

# Máy 4 · Bybit
WORKER_ID=worker-4 EXCHANGE=bybit docker compose --env-file deploy/.env.worker -p linuxck-bybit -f deploy/worker.compose.yml up --build -d
```

Kiểm tra trạng thái Worker và dữ liệu trên dashboard. Để xem log hoặc dừng một máy, dùng lại lệnh Compose của máy đó và thay `up --build -d` bằng `logs --tail=100` hoặc `stop`. Lệnh `stop` giữ dữ liệu trong volume.

Đợt thử nghiệm cục bộ thu được dữ liệu thật từ Binance và OKX. Bybit trả HTTP 403 tại môi trường thử nghiệm. Kịch bản phục hồi Master đã qua mô phỏng cục bộ. Triển khai trên bốn máy thật vẫn cần kiểm tra.

[Chi tiết vận hành và kiểm thử](docs/DISTRIBUTED.md) · [Bàn giao](docs/HANDOFF.md) · [Phát hành](docs/RELEASE.md)
