# LinuxCK Worker 2

Worker độc lập lấy dữ liệu công khai của Binance Spot cho BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT và ADAUSDT. Repo gốc mô tả kiến trúc Máy 1 điều phối qua RabbitMQ, lưu PostgreSQL và ba worker liên lạc qua Tailscale. Mô-đun này có thể chạy bằng Python từ thư mục gốc của repo.

## Chạy trên Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r worker/requirements.txt
.venv/bin/python -m worker collect --once
.venv/bin/python -m worker collect --seconds 315 >test-results/live.json 2>test-results/live.log
.venv/bin/python -m worker stats --session test-results/live.json
.venv/bin/python -m worker export price_snapshots test-results/live_prices.csv
.venv/bin/python -m pytest worker/tests -q -s
```

Trên Windows tạo môi trường bằng `py -3 -m venv .venv` và thay `.venv/bin/python` bằng `.venv\Scripts\python.exe`. Cần Python 3.10 trở lên. Tuỳ chỉnh lịch trong `worker/config.json` hoặc truyền `--config FILE` trước tên lệnh. `--database FILE` chọn một tệp SQLite khác. Hết phiên, CLI thoát. Mỗi công việc đã bắt đầu có thể kết thúc sau mốc dừng lập lịch nếu phải chờ API hoặc retry.

## Dữ liệu và giao thức

- `Job(job_id, kind)` xác định một lần thu thập. Các loại là `price`, `ticker`, `kline`. Adapter về sau nên truyền lại cùng `job_id` khi giao lại cùng một công việc.
- `MarketResult.to_message()` sinh JSON phiên bản 1, gồm `worker_id`, `exchange`, `job_id`, `collection_run_id`, `kind`, `symbol`, `price`, `collected_at`, `source_timestamp`, `status`, `schema_version` và `data`. `price` là chuỗi thập phân, với nến thì là giá đóng cửa. `data` chứa số liệu riêng của từng loại.
- Binance ticker giá hiện tại không có timestamp nguồn, nên trường đó là JSON `null` / SQL `NULL`. Ticker 24 giờ có mốc mở và đóng cửa sổ thống kê. Với nến, chỉ các nến đã đóng theo giờ máy chủ Binance được lưu, và `source_timestamp` là giờ đóng nến.
- `ResultSink` cung cấp giao diện kiểm tra idempotency, lưu kết quả và ghi lỗi. `Storage` thực hiện giao diện này với SQLite WAL. Bảng nến dùng khóa exchange/symbol/interval/open_time. SQLite giữ dữ liệu cũ khi gặp nến trùng. Job thành công được ghi trong cùng transaction với dữ liệu thị trường.
- Lịch mặc định là 60 giây cho giá và 300 giây cho ticker 24 giờ và nến. Với năm symbol, request weight khởi động là 24 (ping, time, exchangeInfo, giá BTC) và lần thu thập đủ ba loại là 27. Client sử dụng HTTP GET và TLS qua cấu hình HTTPS có sẵn của máy. Xem [tài liệu Binance Spot](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints).

## Dữ liệu thử nghiệm

Chạy mock bằng pytest, SQLite được tạo dưới thư mục tạm của pytest. Phiên thật mặc định lưu vào `worker/trial/live.sqlite3`. Để chạy lại phép kiểm tra bằng chứng của phiên thật, đặt `BINANCE_LIVE_RESULTS=test-results/live.json` và `BINANCE_LIVE_DATABASE=worker/trial/live.sqlite3` trước lệnh pytest. Lệnh `stats --session` ghép thống kê dữ liệu hiện tại với độ trễ HTTP của phiên được chỉ định.
