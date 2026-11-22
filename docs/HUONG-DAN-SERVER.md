# Cài LinuxCK trên máy 1 — Máy chủ

Thực hiện trong terminal **Ubuntu của máy 1**. Bản cài là `0.1.0-rc.2` trên Docker Hub. Khởi động máy chủ trước khi các thành viên bật worker.

| Việc cần làm | Xem phần |
| --- | --- |
| Cài máy chủ lần đầu | Bước 1 đến 4 |
| Giao cấu hình cho ba worker và kiểm tra giá | Bước 5 |
| Bật Beszel hoặc Telegram | Bước 6 và 7 |
| Bật lại, xem log hoặc sửa lỗi | Bước 8 và 9 |

## 1. Kiểm tra Ubuntu, Docker và Tailscale

Chạy ba lệnh sau trên máy 1.

```sh
docker info --format '{{.ServerVersion}}'
docker compose version
tailscale ip -4
```

Bạn cần thấy phiên bản Docker Engine, phiên bản Compose và một IP Tailscale. Ghi lại IP cuối cùng để điền `MASTER_BIND`. Nếu Docker báo thiếu quyền, thử `sudo docker info`. Nếu lệnh đó chạy được, dùng `sudo` trước các lệnh `docker` trong tài liệu.

### 1.1 Cài Docker Engine và Docker Compose trên VM mới

Chỉ chạy phần này khi VM chưa có Docker. Dùng terminal Ubuntu có quyền quản trị. Nếu đang đăng nhập bằng `root`, có thể bỏ `sudo` trong các lệnh dưới đây.

```sh
sudo apt update
sudo apt install -y ca-certificates curl nano python3

docker_install=$(mktemp)
curl -fsSL https://get.docker.com -o "$docker_install" && sudo sh "$docker_install"
rm -f -- "$docker_install"

sudo systemctl enable --now docker
sudo docker info --format '{{.ServerVersion}}'
sudo docker compose version
```

Hai lệnh cuối cần in phiên bản Docker Engine và Docker Compose. Lệnh `enable --now` bật Docker ngay và cho Docker khởi động cùng VM. Nếu đã cài Docker từ kho Docker chính thức và chỉ thiếu Compose, chạy `sudo apt update && sudo apt install -y docker-compose-plugin` rồi kiểm tra lại. [Cài Docker Engine trên Ubuntu](https://docs.docker.com/engine/install/ubuntu/#install-using-the-convenience-script) · [Cài riêng Docker Compose](https://docs.docker.com/compose/install/linux/)

### 1.2 Cài và kết nối Tailscale

Chỉ chạy khối cài đặt nếu lệnh `tailscale` chưa có trên VM.

```sh
sudo apt update
sudo apt install -y ca-certificates curl

tailscale_install=$(mktemp)
curl -fsSL https://tailscale.com/install.sh -o "$tailscale_install" && sudo sh "$tailscale_install"
rm -f -- "$tailscale_install"

sudo systemctl enable --now tailscaled
```

Nếu VM chưa tham gia mạng Tailscale của nhóm, chạy lệnh sau.

```sh
sudo tailscale up
```

Mở liên kết đăng nhập mà lệnh hiện ra bằng trình duyệt trên Windows. Đăng nhập bằng tài khoản được quản trị viên mời vào **cùng tailnet của nhóm**. Khi đã đăng nhập, quay lại terminal Ubuntu để kiểm tra.

```sh
tailscale status
tailscale ip -4
```

Kết quả cần có IP Tailscale **của chính VM đang cài**. [Cài và kết nối Tailscale trên Linux](https://tailscale.com/docs/install/linux)
Trên máy 1, ghi lại IP vừa nhận để điền `MASTER_BIND` ở bước 3 và gửi IP này cho ba worker.
## 2. Pull image và tạo bộ cài

Tạo thư mục cài trên máy 1 và pull image máy chủ.

```sh
mkdir -p ~/linuxck-server
cd ~/linuxck-server
docker pull bachcp10/linuxck-server:0.1.0-rc.2
```

Vẫn ở `~/linuxck-server`, chạy lệnh tạo file một lần. Lệnh tạo file trong thư mục hiện tại. Hai lệnh `mv` đặt tên `compose.yaml` và `.env` để các lần sau có thể chạy Docker Compose từ chính thư mục này.

```sh
image=bachcp10/linuxck-server:0.1.0-rc.2
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/setup" "$image" python /opt/linuxck/setup.py "$image"
mv -n master.compose.yml compose.yaml
mv -n .env.master .env
ls -la
```

Kiểm tra thấy các file sau. File bắt đầu bằng dấu chấm hiện khi dùng `ls -la`.

```text
~/linuxck-server/
├── compose.yaml
├── .env
├── beszel-hub.compose.yml
├── .env.beszel-hub
├── beszel-agent.compose.yml
└── .env.beszel-agent
```

Các file này được tạo ngay trên Ubuntu. Nếu đã cài theo hướng dẫn cũ trong `~/linuxck`, cứ dùng thư mục và tên file đang chạy để giữ đúng volume. Xem [lệnh cho bộ cài cũ](RELEASE.md#giữ-bộ-cài-cũ).

## 3. Điền IP Tailscale của máy 1

Mở file cấu hình trên máy 1.

```sh
cd ~/linuxck-server
nano .env
```

| Dòng trong `.env` | Điền gì |
| --- | --- |
| `MASTER_BIND` | Thay `127.0.0.1` bằng đúng IP từ `tailscale ip -4`. |
| `LINUXCK_SERVER_IMAGE` | Giữ tag `bachcp10/linuxck-server:0.1.0-rc.2`. |
| `RABBITMQ_PASSWORD` | Giữ mật khẩu đã sinh. Gửi riêng giá trị này cho người cài worker. |
| `POSTGRES_PASSWORD`, `POSTGRES_DSN`, `MASTER_ADDRESS` | Giữ nguyên. Địa chỉ `postgres` và `rabbitmq` trong file là tên dịch vụ nội bộ của máy 1. |
| `TELEGRAM_ENABLED` | Giữ `false` cho lần chạy đầu. |

Ví dụ nếu IP Tailscale của máy 1 là `100.64.10.20`, điền `MASTER_BIND=100.64.10.20`. Dùng IP thật của máy bạn. Trong nano, nhấn **Ctrl+O**, **Enter**, rồi **Ctrl+X** để lưu và thoát.

## 4. Bật máy chủ và mở dashboard

```sh
cd ~/linuxck-server
docker compose config --quiet
docker compose up -d
docker compose ps -a
```

`config --quiet` không in gì khi cấu hình hợp lệ. Sau khi bật, kiểm tra `postgres`, `rabbitmq` và `backend` lần lượt lên `healthy`. Docker sẽ lấy thêm image PostgreSQL và RabbitMQ khi máy chưa có.

Từ máy 1, nếu đã có curl, kiểm tra API bằng lệnh sau.

```sh
curl -fsS "http://$(tailscale ip -4):8080/health"
```

Kết quả cần thấy là `{"status":"ok"}`. Từ trình duyệt trên thiết bị đã vào cùng mạng Tailscale, mở `http://IP_MAY_1:8080` với IP thật. Lúc chưa khởi động worker, dashboard có thể hiện **0/3 Worker online**.

## 5. Giao cấu hình và kiểm tra dữ liệu

Gửi [hướng dẫn worker](HUONG-DAN-WORKER.md) cho ba thành viên. Gửi riêng IP Tailscale của máy 1 và giá trị `RABBITMQ_PASSWORD`. Mỗi máy dùng đúng cặp dưới đây.

| Máy | ID | Nguồn giá |
| --- | --- | --- |
| 2 | `worker-2` | Binance |
| 3 | `worker-3` | OKX |
| 4 | `worker-4` | Bybit |

Khi cả ba máy kết nối, dashboard hiện **3/3 Worker online**. Kiểm tra thêm bảng giá của từng sàn để xác nhận máy chủ đang nhận dữ liệu. Nếu cần đối chiếu trực tiếp PostgreSQL, chạy lệnh sau trên máy 1.

```sh
cd ~/linuxck-server
docker compose exec -T postgres \
  psql -U linuxck -d linuxck -c \
  'SELECT exchange, COUNT(DISTINCT symbol) AS so_ma, MAX(collected_at) AS cap_nhat_cuoi FROM market_prices GROUP BY exchange ORDER BY exchange;'
```

Khi cả ba nguồn thu thập thành công, kết quả có 3 dòng và `so_ma` bằng 5 cho mỗi sàn. Chạy lại sau khoảng một phút để xem `cap_nhat_cuoi` đã tiến lên chưa.

## 6. Bật Beszel để giám sát bốn VM

Hub là trang quản trị chạy trên máy 1. Mỗi VM được giám sát chạy một Agent riêng, kể cả máy 1. Agent và ứng dụng LinuxCK chạy độc lập.

### 6.1 Trên máy 1, mở Beszel Hub

Nếu VM này đã chạy Beszel Hub của Neon trên cổng `8090`, mở Hub đang chạy và tiếp tục ở mục 6.2.

```sh
cd ~/linuxck-server
tailscale ip -4
nano .env.beszel-hub
```

Điền hai dòng sau bằng **IP Tailscale của máy 1**. Ví dụ dưới đây dùng IP minh họa.

```dotenv
BESZEL_BIND=100.64.10.20
BESZEL_HUB_URL=http://100.64.10.20:8090
```

```sh
docker compose -p linuxck-beszel-hub --env-file .env.beszel-hub -f beszel-hub.compose.yml up -d
docker compose -p linuxck-beszel-hub --env-file .env.beszel-hub -f beszel-hub.compose.yml ps
curl -fsS "http://$(tailscale ip -4):8090/api/health"
```

Mở `BESZEL_HUB_URL` trên trình duyệt của thiết bị cùng Tailscale. Tạo tài khoản quản trị bằng email và mật khẩu riêng ở lần mở đầu, rồi đăng nhập.

### 6.2 Trong Hub, thêm từng VM và lấy cấu hình

Trên **từng VM**, chạy `tailscale ip -4` để lấy IP **của VM đó**. Trong Beszel Hub, bấm **Add System** và thêm lần lượt các máy.

| Trường trong Hub | Điền gì |
| --- | --- |
| **Name** | `linuxck-server`, `linuxck-worker-2`, `linuxck-worker-3` hoặc `linuxck-worker-4`. |
| **Host / IP** | IP Tailscale của VM đang thêm. Ví dụ khi thêm máy 3, dùng IP máy 3. |
| **Port** | Giữ giá trị mặc định `45876` nếu biểu mẫu hiển thị. Agent kết nối ra Hub qua WebSocket ở cổng `8090`. |

Trong hộp **Add System**, chọn phần **Docker** và tìm cấu hình Agent. Sao chép cả giá trị **KEY** và **TOKEN**, sau đó bấm **Add System** để lưu máy. KEY là khóa công khai, sao chép đầy đủ cả tiền tố `ssh-ed25519`. TOKEN là giá trị cấp cho VM đang thêm.

Gửi riêng cho người cài từng VM ba giá trị **URL Hub** (URL của máy 1, cổng `8090`), **KEY** và **TOKEN** của đúng VM. Nếu VM đó đã có Agent Neon báo **Up** trên Hub đang dùng, xem giám sát trên mục VM hiện có.

### 6.3 Trên máy 1, cấu hình và bật Agent

Trên máy 1, dùng bộ file đã được tạo ở bước 2 để chuẩn bị thư mục Agent riêng.

```sh
mkdir -p ~/linuxck-monitor
cp -n ~/linuxck-server/beszel-agent.compose.yml ~/linuxck-monitor/compose.yaml
cp -n ~/linuxck-server/.env.beszel-agent ~/linuxck-monitor/.env
cd ~/linuxck-monitor
nano .env
```

Điền các dòng sau. Thay URL minh họa, KEY và TOKEN bằng giá trị lấy ở mục 6.2 của mục **linuxck-server**.

```dotenv
COMPOSE_PROJECT_NAME=linuxck-beszel-agent
BESZEL_HUB_URL=http://100.64.10.20:8090
BESZEL_KEY='DAN_TOAN_BO_KEY_CUA_MAY_1'
BESZEL_TOKEN='DAN_TOKEN_CUA_MAY_1'
```

Giữ dấu nháy đơn quanh KEY và TOKEN. Trong nano, lưu bằng **Ctrl+O**, **Enter**, rồi **Ctrl+X**.

```sh
cd ~/linuxck-monitor
chmod 600 .env
docker compose config --quiet
docker compose up -d
docker compose logs --tail 30 beszel-agent
```

Kiểm tra log kết nối WebSocket và xác nhận **linuxck-server** hiện **Up** trên Hub, có số liệu CPU/RAM. Máy 2–4 dùng [mục Agent trong hướng dẫn worker](HUONG-DAN-WORKER.md#6-bật-beszel-agent). [Cách lấy thông tin Agent](https://beszel.dev/guide/agent-installation)

## 7. Bật Telegram trên máy 1

### 7.1 Lấy bot token và chat ID

1. Trong Telegram, mở [@BotFather](https://t.me/BotFather), gửi `/newbot` và làm theo yêu cầu đặt tên. Sao chép token được trả về.
2. Mở chat riêng với bot vừa tạo, nhấn **Start** hoặc gửi `/start`. Nếu gửi báo cáo vào nhóm, thêm bot vào nhóm và gửi một lệnh dành cho bot, ví dụ `/start@TEN_BOT_CUA_BAN`.
3. Trên **máy 1**, chạy lệnh dưới đây. Khi thấy câu hỏi, dán token rồi nhấn **Enter**. Token được nhập ẩn. Lệnh dùng curl và Python 3 trên Ubuntu để in tên chat và ID mà Bot API trả về.

```bash
read -rs -p 'Nhap bot token: ' bot_token
printf '\n'
printf 'url = "https://api.telegram.org/bot%s/getUpdates"\n' "$bot_token" |
  curl -fsS --config - |
  python3 -c 'import json, sys; chats = {u["message"]["chat"]["id"]: u["message"]["chat"] for u in json.load(sys.stdin)["result"] if "message" in u}; [print(chat["id"], chat.get("title") or chat.get("username") or chat.get("first_name", "")) for chat in chats.values()]'
unset bot_token
```

Chọn ID của đúng nơi muốn nhận thông báo, giữ cả dấu trừ nếu ID của nhóm là số âm. Nếu lệnh không in chat nào, gửi lại `/start` cho bot trong chat đích rồi chạy lại. [Tạo bot Telegram](https://core.telegram.org/bots/tutorial) · [Cách Bot API trả cập nhật](https://core.telegram.org/bots/api#getupdates)

### 7.2 Điền cấu hình và áp dụng

```sh
cd ~/linuxck-server
nano .env
```

```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=DAN_TOKEN_TU_BOTFATHER
TELEGRAM_CHAT_ID=DAN_ID_CUA_CHAT_DICH
```

Lưu file rồi áp dụng trên máy 1.

```sh
docker compose config --quiet
docker compose up -d backend
```

Khi có dữ liệu đủ để so sánh giữa các sàn, kiểm tra tin nhắn trong chat đã chọn và mục thông báo trên dashboard. Trạng thái `sent` nghĩa là Telegram đã chấp nhận gửi. Khi muốn tắt, đặt `TELEGRAM_ENABLED=false` rồi chạy lại `docker compose up -d backend`. Giữ bot token trên máy 1.

## 8. Bật lại, cập nhật hoặc dừng máy chủ

Vào thư mục máy chủ trước mỗi lần thao tác.

```sh
cd ~/linuxck-server
```

| Tình huống | Lệnh |
| --- | --- |
| Lần trước đã dùng `stop`, container vẫn còn | `docker compose start` |
| Vừa cài, vừa sửa `.env` hoặc container đã bị xóa | `docker compose up -d` |
| Dừng máy chủ và giữ dữ liệu | `docker compose stop` |
| Xem container đang chạy hay đã dừng | `docker compose ps -a` |
| Xem log backend, PostgreSQL và RabbitMQ | `docker compose logs --tail 80 backend postgres rabbitmq` |

Khi chỉ bật lại sau `stop`, dùng `start` và giữ cấu hình đang có. Khi đổi tag image, sửa dòng `LINUXCK_SERVER_IMAGE` rồi chạy `docker compose pull` và `docker compose up -d` trong thư mục đang dùng.

Beszel Hub và Agent dùng `restart: unless-stopped`. Sau lần bật đầu tiên bằng `up -d`, khi VM bật lại, Docker tự khởi động những container Beszel đang hoạt động trước đó nếu dịch vụ Docker cũng khởi động cùng Ubuntu. Agent kết nối về Hub khi Tailscale đã vào mạng.

Nếu đã chủ động dừng Agent bằng `docker compose stop`, bật lại từ thư mục giám sát.

```sh
cd ~/linuxck-monitor
docker compose start
```

Dùng `docker compose stop` ngay trong `~/linuxck-monitor` khi chỉ muốn dừng Agent. Beszel Hub trên máy 1 dùng lệnh sau nếu Hub đã dừng và container vẫn còn.

```sh
cd ~/linuxck-server
docker compose -p linuxck-beszel-hub --env-file .env.beszel-hub -f beszel-hub.compose.yml start
```


Để dừng riêng Hub và giữ lịch sử giám sát, dùng lệnh sau trên máy 1.

```sh
cd ~/linuxck-server
docker compose -p linuxck-beszel-hub --env-file .env.beszel-hub -f beszel-hub.compose.yml stop
```
## 9. Xử lý lỗi thường gặp

| Hiện tượng | Kiểm tra |
| --- | --- |
| Không thấy `.env` | Chạy `pwd` và `ls -la` trong `~/linuxck-server`. Nếu chưa có file ở lần cài mới, chạy bước 2. |
| Lỗi `cannot assign requested address` | So `MASTER_BIND` với `tailscale ip -4` của máy 1. |
| Docker báo cổng đã được dùng | Kiểm tra các container hiện có bằng `docker ps` để tìm dịch vụ đang dùng cổng 5672 hoặc 8080 trên cùng địa chỉ. |
| API trả `503` | Xem trạng thái và log PostgreSQL, rồi kiểm tra `POSTGRES_DSN` trong `.env`. |
| Worker online nhưng bảng giá còn thiếu | Xem log của worker theo sàn bị thiếu. Đối chiếu thời điểm thu thập và số mã ở bước 5. |
| Máy 1 mở được dashboard nhưng Windows không mở được | Kiểm tra Windows đã vào cùng mạng Tailscale và trình duyệt đang dùng IP Tailscale của máy 1. |
