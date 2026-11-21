# Hướng dẫn làm việc trong LinuxCK

## Khi bắt đầu

- Đọc `README.md`, `docs/HANDOFF.md` và nội dung Issue hoặc pull request được giao. Kiểm tra nhánh hiện tại và các thay đổi đang có trước khi sửa.
- Bám vào phần việc được giao. Khi thay đổi giao tiếp giữa server và worker, cập nhật tài liệu về định dạng dữ liệu và thông báo trong pull request.
- Kiểm tra thay đổi bằng lệnh có thể chạy lại. Ghi kết quả thực tế và các mục còn cần kiểm tra trong bản bàn giao.

## Khi bàn giao

- Ghi phần đã hoàn thành, tệp liên quan, lệnh kiểm thử và kết quả, vấn đề còn mở, bước tiếp theo. Đặt chi tiết của từng đầu việc trên Issue hoặc pull request và cập nhật các mốc chung trong `docs/HANDOFF.md` khi phù hợp.
- Dùng nhánh riêng cho từng phần công việc khi nhóm bắt đầu cộng tác. Chuẩn bị pull request để người phụ trách kiểm tra trước khi gộp vào nhánh chính.
- Giữ khóa API, bot token, thông tin xác thực Tailscale và mật khẩu ngoài Git và Docker image. Tệp cấu hình mẫu chỉ dùng giá trị minh họa.
- Nhóm có thể build và kiểm thử Docker tại máy. Chủ dự án duyệt và phát hành image lên Docker Hub theo `docs/RELEASE.md`.
