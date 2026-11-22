# Tiến độ và bàn giao

## Giai đoạn hiện tại

- Hệ thống hiện thu thập giá Spot từ Binance, OKX và Bybit trên một máy chủ và ba worker Ubuntu Server.
- Hai image `0.1.0-rc.2` đã phát hành trên Docker Hub. Xem [hướng dẫn máy chủ](HUONG-DAN-SERVER.md) và [hướng dẫn worker](HUONG-DAN-WORKER.md) để cài trên VM.
- Đã kiểm tra luồng máy thu thập gửi giá về PostgreSQL trong WSL. Cần triển khai bốn VM qua Tailscale và kiểm tra giám sát, Telegram trên môi trường của nhóm.

## Phần việc để giao sau

| Phần việc | Phạm vi |
|---|---|
| Điều phối | Lịch giao việc, RabbitMQ, PostgreSQL và triển khai Máy 1 |
| Dữ liệu | Nguồn giá, chuẩn hóa dữ liệu và phát lại dữ liệu mẫu |
| Dự báo | Worker gọi TimeGPT, ghi kết quả và đánh giá dự báo |
| Vận hành | Beszel, Tailscale, Telegram và kiểm thử toàn luồng |

## Mẫu ghi cuối phiên

- Đã làm
- Nhánh hoặc pull request
- Lệnh kiểm thử và kết quả
- Việc đang vướng
- Bước tiếp theo

## Thử nghiệm cục bộ bốn vai trò

Mã ứng dụng chung ở `distributed/`, cấu hình Compose ở `deploy/`. Hướng dẫn vận hành, giao thức outbox và phạm vi thử nghiệm nằm trong [LinuxCK bốn vai trò](DISTRIBUTED.md). Mã Worker Binance độc lập từ thử nghiệm đầu vẫn có thể chạy riêng.

## Chuẩn bị thử nghiệm trên VMware

- Dockerfile có hai target `server` và `worker`. Máy 1 chọn `LINUXCK_SERVER_IMAGE`. Cả ba worker chọn cùng `LINUXCK_WORKER_IMAGE` và đặt `WORKER_ID`, `EXCHANGE` theo từng máy.
- Đã thêm Compose riêng cho Beszel Hub và Agent. Khi triển khai, cấu hình IP Tailscale và token của từng máy. Telegram có sẵn trên máy 1 và mặc định tắt.
- Cách kiểm tra và phát hành thủ công có trong [hướng dẫn Docker Hub](RELEASE.md).

### Kết quả kiểm thử bản dùng chung image trước khi tách

- Docker WSL build thành công từ `deploy/Dockerfile` cho `linux/amd64`. Image có mã `sha256:9d770478ffe88d0e1dde66f2caddd8bff0f475416b8c858ee191a7cecdc1c3a9`.
- Lệnh kiểm thử `docker run --rm --network none linuxck:0.1.0-rc.1 python -m pytest -q -p no:cacheprovider worker/tests distributed/tests/test_core.py` cho kết quả 37 test đạt và 1 test bỏ qua vì cần báo cáo thu thập Binance thật của CLI.
- Đã chạy `docker compose config --quiet` và `up -d --no-build` với máy chủ, ba worker và hai dịch vụ Beszel trong thư mục chỉ có Compose và cấu hình thử. PostgreSQL nhận đủ 5 mã từ mỗi sàn. Beszel Hub nhận số liệu của một Agent qua WebSocket.
- Smoke test trên WSL dùng vùng lưu tạm cho PostgreSQL, RabbitMQ và dữ liệu thu thập. Cần kiểm tra volume lâu dài, bốn Agent qua Tailscale và gửi Telegram thật khi triển khai trên VMware.

### Kết quả kiểm thử hai image 0.1.0-rc.1

- `linuxck-server:0.1.0-rc.1` có mã image `sha256:22a1219becb793b1b871733a866e6fd0aa6146e5d1e710dc99e6c42597798fcc`.
- `linuxck-worker:0.1.0-rc.1` có mã image `sha256:85de7e2730f640c6dd9f30146098e36394a6bd1744255156a95c7757d82b4ff1`.
- Đã chạy hai lệnh build theo [hướng dẫn Docker Hub](RELEASE.md), sau đó kiểm tra cấu hình bằng `docker compose config --quiet` và khởi động bằng `docker compose up -d --no-build` trên WSL. Đã đối chiếu mã image của máy chủ và từng worker. Máy chủ trả trạng thái `ok`, PostgreSQL nhận đủ 5 mã từ mỗi sàn Binance, OKX và Bybit.
- Chạy `docker run --rm --network none linuxck-worker:0.1.0-rc.1 python -m pytest -q -p no:cacheprovider worker/tests distributed/tests/test_core.py` cho kết quả 37 test đạt và 1 test bỏ qua vì cần báo cáo thu thập thật từ Binance.

### Đã phát hành lên Docker Hub

- [Image máy chủ](https://hub.docker.com/r/bachcp10/linuxck-server/tags) dùng tag `bachcp10/linuxck-server:0.1.0-rc.1` và manifest `sha256:22a1219becb793b1b871733a866e6fd0aa6146e5d1e710dc99e6c42597798fcc`.
- [Image dùng chung cho ba worker](https://hub.docker.com/r/bachcp10/linuxck-worker/tags) dùng tag `bachcp10/linuxck-worker:0.1.0-rc.1` và manifest `sha256:85de7e2730f640c6dd9f30146098e36394a6bd1744255156a95c7757d82b4ff1`.
- Docker Hub cấp quyền pull công khai cho cả hai tag. Đã đối chiếu digest từ Docker Hub với image đã kiểm thử trên WSL.

### Kết quả kiểm thử tạo cấu hình từ image 0.1.0-rc.2

- `linuxck-server:0.1.0-rc.2` có mã image `sha256:4870bfa77e675e39bebd100f5f7103ce0caf5e27a0063f2e5388488e86a41d56`.
- `linuxck-worker:0.1.0-rc.2` có mã image `sha256:0caaebb8b58a81798e5a0068584a9353c206b6c23d789c2bece4e20659ecc679`.
- Đã chạy `python /opt/linuxck/setup.py "$image"` bằng Docker theo [hướng dẫn phát hành](RELEASE.md) trên hai thư mục trống. Hai image tạo đúng bộ Compose và `.env` tương ứng. Mật khẩu sinh trên máy chủ khớp chuỗi kết nối. File `.env` có quyền `600` và giữ nguyên khi chạy lại.
- Kiểm tra Compose, khởi động máy chủ và ba worker bằng WSL. PostgreSQL nhận đủ 5 mã từ mỗi sàn. Bộ test Python có 37 test đạt và 1 test bỏ qua.
- Đã phát hành hai image `0.1.0-rc.2` lên Docker Hub ([máy chủ](https://hub.docker.com/r/bachcp10/linuxck-server/tags) và [worker](https://hub.docker.com/r/bachcp10/linuxck-worker/tags)). Đã xác minh cả hai tag pull công khai và digest trùng image đã kiểm thử.

### Hướng dẫn cài trên VM mới

- Đã thêm [hướng dẫn máy chủ](HUONG-DAN-SERVER.md) và [hướng dẫn worker](HUONG-DAN-WORKER.md), gồm lệnh pull, tạo cấu hình từ image, bật dịch vụ và đối chiếu giá.
- Đã kiểm tra cú pháp các lệnh shell và chạy theo hướng dẫn trên WSL. Cả hai image pull được, tạo đúng bộ file theo vai trò và qua `docker compose config --quiet`. Hai hướng dẫn có bảng chọn việc, danh sách file tạo sau khi pull, các dòng cấu hình cho từng máy, dấu hiệu chạy đúng và cách xử lý lỗi thường gặp. Đã kiểm tra lại 11 khối lệnh máy chủ và 10 khối lệnh worker, gồm chạy pull, tạo file và kiểm tra Compose trên WSL. Cần đối chiếu trạng thái bốn máy khi cài thật qua Tailscale.

### Bố cục cài đặt theo từng vai trò và thao tác hằng ngày

- Hướng dẫn máy mới dùng `~/linuxck-server`, `~/linuxck-worker` và `~/linuxck-monitor`. Bộ cài cũ giữ thư mục và tên dự án Compose đang dùng.
- Đã kiểm tra trên WSL rằng máy chủ và worker chạy với `compose.yaml` và `.env` mặc định. Các lệnh `docker compose up -d`, `stop` và `start` hoạt động, với cùng ID container trước và sau khi bật lại.
- Đã kiểm tra cấu hình Agent ánh xạ đúng URL Hub, KEY và TOKEN từ `.env`. Đăng ký Beszel trên bốn VM và bật Telegram thật cần được kiểm tra khi cấu hình trên các máy của nhóm.

### Cài công cụ trước khi chạy LinuxCK

- Cả hai hướng dẫn VM mới có lệnh cài Docker Engine, Compose và Tailscale, cách bật dịch vụ lúc khởi động và cách vào tailnet của nhóm. VM đã có công cụ có thể bỏ qua phần cài tương ứng.
- Các khối lệnh cài đặt đã qua kiểm tra cú pháp Bash và được đối chiếu với tài liệu chính thức. Các gói được cài trên từng VM cần sử dụng.
