# Cài LinuxCK trên máy 2, 3 hoặc 4 — Worker

Mỗi thành viên chạy hướng dẫn này trong terminal **Ubuntu của VM mình**. Ba máy dùng chung image `0.1.0-rc.2` và mỗi máy đặt một ID cùng một sàn.

| Việc cần làm | Xem phần |
| --- | --- |
| Cài worker lần đầu | Bước 1 đến 4 |
| Xem worker đã gửi dữ liệu về chưa | Bước 5 |
| Bật giám sát Beszel | Bước 6 |
| Bật lại, đổi cấu hình hoặc xử lý lỗi | Bước 7 và 8 |

## 1. Lấy đúng thông tin của máy mình

Chờ [máy chủ LinuxCK](HUONG-DAN-SERVER.md) khởi động. Người phụ trách máy chủ sẽ gửi bạn **IP Tailscale của máy 1** và **mật khẩu RabbitMQ**. Dùng cặp ID và sàn theo bảng sau.

| Máy đang cài | `WORKER_ID` | `EXCHANGE` |
| --- | --- | --- |
| Máy 2 | `worker-2` | `binance` |
| Máy 3 | `worker-3` | `okx` |
| Máy 4 | `worker-4` | `bybit` |

```sh
docker info --format '{{.ServerVersion}}'
docker compose version
tailscale ip -4
```

Ba lệnh trên phải trả về phiên bản Docker Engine, phiên bản Compose và IP Tailscale **của VM worker**. IP này khác IP máy 1. Kiểm tra hai máy đã vào cùng mạng. Nếu Docker báo thiếu quyền, thử `sudo docker info`, rồi dùng `sudo` trước các lệnh `docker` nếu cần.

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
Trên worker, nhập IP Tailscale của máy 1 vào lệnh sau để xác nhận hai VM nhìn thấy nhau. Thay `100.64.10.20` bằng IP thật của máy 1.

```sh
tailscale ping 100.64.10.20
```
## 2. Pull image chung và tạo file tại VM

```sh
mkdir -p ~/linuxck-worker
cd ~/linuxck-worker
docker pull bachcp10/linuxck-worker:0.1.0-rc.2
```

Vẫn ở `~/linuxck-worker`, chạy lệnh tạo file một lần. Hai lệnh `mv` đặt tên `compose.yaml` và `.env` để các lần sau có thể chạy Docker Compose từ chính thư mục này.

```sh
image=bachcp10/linuxck-worker:0.1.0-rc.2
docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$PWD:/setup" "$image" python /opt/linuxck/setup.py "$image"
mv -n worker.compose.yml compose.yaml
mv -n .env.worker .env
ls -la
```

Kiểm tra thấy các file sau ngay trên worker.

```text
~/linuxck-worker/
├── compose.yaml
├── .env
├── beszel-agent.compose.yml
└── .env.beszel-agent
```

File bắt đầu bằng dấu chấm hiện khi dùng `ls -la`. Các máy có cùng bộ file, giá trị trong `.env` sẽ được điền theo từng máy ở bước kế tiếp. Nếu đã cài theo hướng dẫn cũ trong `~/linuxck`, giữ thư mục và tên file đó. Xem [lệnh cho bộ cài cũ](RELEASE.md#giữ-bộ-cài-cũ).

## 3. Chỉ sửa ba dòng trong `.env`

```sh
cd ~/linuxck-worker
nano .env
```

1. Đặt `WORKER_ID` theo bảng ở bước 1.
2. Đặt `EXCHANGE` ở đúng hàng, viết thường.
3. Trong `MASTER_ADDRESS`, thay `MAT_KHAU_RABBITMQ` bằng mật khẩu được cấp và `IP_TAILSCALE_MAY_1` bằng **IP của máy chủ**. Giữ cổng `5672` và phần cuối `/%2F`.

Ví dụ dưới đây dành cho máy 3. Máy 2 và 4 chọn ID và sàn ở đúng hàng của mình. Thay hai giá trị mẫu trong địa chỉ trước khi lưu.

```dotenv
WORKER_ID=worker-3
EXCHANGE=okx
MASTER_ADDRESS=amqp://linuxck:MAT_KHAU_RABBITMQ@IP_TAILSCALE_MAY_1:5672/%2F
```

Giữ nguyên `LINUXCK_WORKER_IMAGE`. Trong nano, nhấn **Ctrl+O**, **Enter**, rồi **Ctrl+X** để lưu và thoát.

## 4. Bật worker

```sh
cd ~/linuxck-worker
docker compose config --quiet
docker compose up -d
docker compose ps -a
```

`config --quiet` không in gì khi cấu hình hợp lệ. Trong `ps -a`, dịch vụ `worker` phải chạy. Trạng thái health có thể hiện `starting` trong lúc nguồn dữ liệu khởi động.

## 5. Xác nhận worker lấy giá và máy chủ nhận được

Trên VM worker, xem log.

```sh
cd ~/linuxck-worker
docker compose logs -f --tail 40 worker
```

Dòng `price stored 5 rows` cho biết worker đã lấy và lưu cục bộ đủ 5 giá ở một lượt. Mặc định giá được lấy khoảng 60 giây một lần. Nhấn **Ctrl+C** để thoát log, worker vẫn chạy.

Mở `http://IP_MAY_1:8080` từ thiết bị cùng mạng Tailscale để kiểm tra phần server. Sàn của bạn phải có trạng thái **Online** và có giá trong bảng. Xem thời điểm của dòng thuộc sàn mình trong lịch sử thu thập và kiểm tra lại sau khoảng một phút.

## 6. Bật Beszel Agent

### 6.1 Nhận ba giá trị từ người giữ Hub

1. Trên VM worker, chạy `tailscale ip -4` và gửi **IP Tailscale của chính VM này** cho người giữ máy 1.
2. Người giữ Hub thêm VM trong **Add System**. Sau đó họ gửi riêng cho bạn **URL Hub**, **KEY** và **TOKEN** của đúng máy. URL Hub sẽ có dạng `http://IP_MAY_1:8090`.
3. Kiểm tra tên máy đi kèm trước khi điền. Ví dụ máy 3 nhận bộ của `linuxck-worker-3`.

Nếu VM đã có Agent Neon và Hub đang dùng hiển thị VM **Up**, dùng mục VM hiện có trên Hub để xem CPU/RAM.

### 6.2 Tạo thư mục riêng và điền `.env`

Trên worker, lấy hai file được tạo sẵn ở bước 2 và chép trong cùng VM.

```sh
mkdir -p ~/linuxck-monitor
cp -n ~/linuxck-worker/beszel-agent.compose.yml ~/linuxck-monitor/compose.yaml
cp -n ~/linuxck-worker/.env.beszel-agent ~/linuxck-monitor/.env
cd ~/linuxck-monitor
nano .env
```

Điền đúng ba giá trị được cấp như mẫu. Dòng `COMPOSE_PROJECT_NAME` giữ nguyên như ví dụ.

```dotenv
COMPOSE_PROJECT_NAME=linuxck-beszel-agent
BESZEL_HUB_URL=http://100.64.10.20:8090
BESZEL_KEY='DAN_TOAN_BO_KEY_CUA_VM_NAY'
BESZEL_TOKEN='DAN_TOKEN_CUA_VM_NAY'
```

- `BESZEL_HUB_URL` là URL của **máy 1** do người giữ Hub gửi, gồm `http://` và cổng `8090`. IP trong mẫu là ví dụ.
- `BESZEL_KEY` nhận cả chuỗi public key, kể cả phần mở đầu `ssh-ed25519`.
- `BESZEL_TOKEN` nhận token của **VM này**. Giữ dấu nháy đơn quanh KEY và TOKEN.

Trong nano, nhấn **Ctrl+O**, **Enter**, rồi **Ctrl+X** để lưu và thoát.

### 6.3 Chạy Agent và kiểm tra

```sh
cd ~/linuxck-monitor
chmod 600 .env
docker compose config --quiet
docker compose up -d
docker compose logs --tail 30 beszel-agent
```

Tìm dòng `WebSocket connected` và nhờ người giữ Hub xác nhận máy đã **Up** và có biểu đồ CPU/RAM. Nếu Agent chưa kết nối, mở `BESZEL_HUB_URL` từ thiết bị trong cùng Tailscale và đối chiếu KEY/TOKEN. [Hướng dẫn Beszel Agent](https://beszel.dev/guide/agent-installation)

## 7. Bật lại, cập nhật hoặc dừng worker

Vào đúng thư mục worker trước khi dùng Docker Compose.

```sh
cd ~/linuxck-worker
```

| Tình huống | Lệnh |
| --- | --- |
| Lần trước dùng `stop`, container vẫn còn | `docker compose start` |
| Vừa cài, vừa sửa `.env` hoặc container đã bị xóa | `docker compose up -d` |
| Dừng worker và giữ dữ liệu SQLite | `docker compose stop` |
| Xem worker chạy hay dừng | `docker compose ps -a` |
| Xem 40 dòng log gần nhất | `docker compose logs --tail 40 worker` |

Khi cần nâng cấp, sửa tag ở dòng `LINUXCK_WORKER_IMAGE` trong `.env`, rồi chạy `docker compose pull` và `docker compose up -d` trong thư mục đang dùng.

Agent Beszel chạy riêng trong `~/linuxck-monitor` và dùng `restart: unless-stopped`. Sau lần bật đầu tiên bằng `up -d`, Agent tự chạy lại khi VM bật và Docker khởi động. Agent sẽ nối lại khi cả Tailscale và Hub trên máy 1 sẵn sàng.

Nếu đã chủ động chạy `docker compose stop` để dừng Agent, bật lại bằng lệnh sau.

```sh
cd ~/linuxck-monitor
docker compose start
```

Dùng `docker compose stop` trong `~/linuxck-monitor` nếu chỉ muốn dừng Agent. Dùng `docker compose up -d` ở đó nếu vừa đổi cấu hình Agent.

## 8. Xử lý lỗi thường gặp

| Hiện tượng | Kiểm tra |
| --- | --- |
| Không thấy `.env` hoặc Compose | Chạy `pwd` và `ls -la` trong `~/linuxck-worker`. Nếu chưa tạo file ở lần cài mới, quay lại bước 2. |
| Log báo ID và sàn không khớp | Sửa `WORKER_ID` và `EXCHANGE` theo đúng cùng một hàng ở bước 1, rồi áp dụng lại. |
| Log có giá nhưng dashboard chưa thấy worker | So IP máy 1 và mật khẩu trong `MASTER_ADDRESS`. Kiểm tra Tailscale trên cả hai VM và RabbitMQ trên máy 1. |
| Sàn trả `403` | Ghi tên sàn và thời điểm lỗi cho người phụ trách dữ liệu. Đây là lỗi phản hồi từ nguồn giá nếu log chỉ rõ tên sàn. |
| Agent chưa hiện trên Beszel Hub | Kiểm tra URL hub, KEY và TOKEN của riêng VM này. |
