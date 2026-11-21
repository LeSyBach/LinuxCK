# Kiểm thử và phát hành Docker Hub

- Thành viên build thử trên nhánh của mình và ghi kết quả trong pull request.
- Chủ dự án chọn commit đã duyệt, build image server và image worker, rồi kiểm tra trên môi trường thử nghiệm.
- Kiểm tra một lô dữ liệu mẫu từ lúc giao công việc đến khi có dự báo và cảnh báo Telegram. Thử dừng một worker để kiểm tra việc giao lại công việc.
- Khi đạt kiểm thử, chủ dự án gắn tag phiên bản cho các image vừa kiểm tra và thực hiện `docker push` bằng tài khoản của mình.
- Ghi mã commit, tag image và kết quả kiểm thử. Dùng tag phiên bản cụ thể khi triển khai lên VM.

Hoạt động tự động trên GitHub phục vụ build và kiểm thử. Bước phát hành Docker Hub do chủ dự án thực hiện thủ công.
