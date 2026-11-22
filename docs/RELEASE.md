# Phát hành thử trên Docker Hub

## Build và duyệt image

Chạy trên máy của chủ dự án từ thư mục gốc của mã nguồn. Máy 1 dùng image `linuxck-server`. Ba worker dùng chung image `linuxck-worker` và chọn sàn qua `.env`. PostgreSQL, RabbitMQ và Beszel dùng image của các dự án tương ứng.

```sh
docker build --target server -t linuxck-server:0.1.0-rc.2 -f deploy/Dockerfile .
docker build --target worker -t linuxck-worker:0.1.0-rc.2 -f deploy/Dockerfile .
```

Để chạy thử bằng image vừa build, đặt `LINUXCK_SERVER_IMAGE=linuxck-server:0.1.0-rc.2` cho máy chủ và `LINUXCK_WORKER_IMAGE=linuxck-worker:0.1.0-rc.2` cho worker. Xác nhận máy chủ nhận giá thật từ các worker và PostgreSQL lưu được dữ liệu. Khi đã duyệt, chủ dự án đăng nhập Docker Hub và chạy các lệnh dưới đây.

```sh
docker login
docker tag linuxck-server:0.1.0-rc.2 bachcp10/linuxck-server:0.1.0-rc.2
docker tag linuxck-worker:0.1.0-rc.2 bachcp10/linuxck-worker:0.1.0-rc.2
docker push bachcp10/linuxck-server:0.1.0-rc.2
docker push bachcp10/linuxck-worker:0.1.0-rc.2
```

Ghi mã commit, tag và kết quả thử nghiệm khi phát hành. Bản phát hành ổn định cần kiểm tra lại luồng giao việc, dự báo và Telegram khi các phần đó đã hoàn tất.

## Cài trên các máy Ubuntu Server

Với bản `0.1.0-rc.2`, hãy pull image rồi chạy lệnh tạo cấu hình ngay trên từng VM.

- [Máy 1 — máy chủ](HUONG-DAN-SERVER.md) dùng thư mục `~/linuxck-server` và image `bachcp10/linuxck-server:0.1.0-rc.2`.
- [Máy 2–4 — worker](HUONG-DAN-WORKER.md) dùng thư mục `~/linuxck-worker` và chung image `bachcp10/linuxck-worker:0.1.0-rc.2`.
- Nếu cài Agent Beszel, dùng thư mục riêng `~/linuxck-monitor` trên từng VM. Xem [cách lấy KEY và TOKEN](HUONG-DAN-SERVER.md#62-trong-hub-thêm-từng-vm-và-lấy-cấu-hình).

Trên bộ cài mới, vào đúng thư mục và dùng `docker compose start` khi bật lại container đã dừng, `docker compose up -d` khi cài mới hoặc sửa cấu hình, và `docker compose stop` khi dừng. Khi nâng cấp, sửa tag trong `.env`, chạy `docker compose pull` rồi `docker compose up -d` trong chính thư mục đó.

### Giữ bộ cài cũ

Nếu VM đã cài trong `~/linuxck` với tên Compose và `.env` theo vai trò, dùng tiếp các file hiện có để giữ volume và cấu hình. Ví dụ để bật lại sau khi dừng, máy 1 dùng lệnh sau.

```sh
cd ~/linuxck
docker compose --env-file .env.master -f master.compose.yml start
```

Worker đã cài dùng lệnh sau.

```sh
cd ~/linuxck
docker compose --env-file .env.worker -f worker.compose.yml start
```

Dùng cùng tham số `--env-file` và `-f` với `stop` để dừng, hoặc với `up -d --no-build` để áp dụng cấu hình mới. Nếu còn dùng image `0.1.0-rc.1`, file mẫu vẫn có trong thư mục [deploy](../deploy/).
