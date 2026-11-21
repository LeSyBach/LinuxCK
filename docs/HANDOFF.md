# Tiến độ và bàn giao

## Giai đoạn hiện tại

- Thiết kế dự kiến đã thống nhất gồm một máy điều phối và ba worker Ubuntu Server trên VMware.
- Chưa có mã ứng dụng hoặc Docker image có thể chạy. Giai đoạn này Codex chuẩn bị nền dự án trước khi các thành viên tham gia.
- Việc đầu tiên của phần triển khai là chốt định dạng công việc và kết quả dự báo, sau đó tạo một luồng chạy thử bằng dữ liệu mẫu.

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
