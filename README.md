# LinuxCK

Đồ án xây dựng hệ thống thu thập dữ liệu chứng khoán, dự báo biến động qua AI API và gửi cảnh báo Telegram trên bốn máy ảo Ubuntu Server chạy bằng VMware.

## Thiết kế dự kiến

- **Máy 1** điều phối công việc bằng RabbitMQ, lưu dữ liệu bằng PostgreSQL, gửi cảnh báo Telegram và chạy Beszel Hub.
- **Máy 2, 3 và 4** chạy cùng một chương trình worker. Mỗi worker lấy công việc theo mã và mốc thời gian, thu thập giá, gọi TimeGPT để dự báo và trả kết quả về Máy 1.
- **Tailscale** kết nối cả bốn VM. Mỗi VM chạy **Beszel Agent** để theo dõi tài nguyên. Trạng thái nghiệp vụ của worker và hàng đợi được theo dõi trên trang quản trị.
- **Docker Compose** quản lý dịch vụ trên các VM. Dự kiến dùng một image cho server và một image chung cho ba worker.

## Làm việc nhóm

Giai đoạn đầu dự án đang chuẩn bị mã nền. Khi có thêm thành viên, mỗi người nhận một đầu việc và mở pull request từ nhánh riêng. Các thành viên dùng cùng định dạng giao việc và trả kết quả giữa server và worker.

- [Hướng dẫn làm việc cho người và AI](AGENTS.md)
- [Tiến độ và bàn giao](docs/HANDOFF.md)
- [Kiểm thử và phát hành Docker Hub](docs/RELEASE.md)
