# Kiểm thử Address Segmentation

Bản nộp nằm trong thư mục Group_01, gồm Group_01.ipynb và Group_01.py. Notebook có tám cell, giữ nguyên nội dung Cell 1, Cell 2 và các comment của mẫu. Mô hình chấm với các danh sách tên đi kèm đề. Đầu ra là ba trường street, ward và province. Trường không tìm được tên phù hợp trả chuỗi rỗng. Khi các ứng viên hợp lệ đồng điểm thì chọn ngẫu nhiên.

Trie lưu tên chuẩn theo từng trường, dãy số và độ dài. Khi tên bị thiếu chữ, Solution lần theo Trie và dừng ở nhánh đã vượt số ký tự được phép bỏ. Ứng viên tìm được đi vào DP cùng các ứng viên khớp chính xác, viết tắt và sai chính tả. DP chọn các đoạn có tổng điểm cao nhất, mỗi trường xuất hiện tối đa một lần.

## Chạy kiểm thử

Chạy từ thư mục bài tập:

```powershell
python -X utf8 edge_cases/run_checks.py --requirements
python -X utf8 edge_cases/run_checks.py --manual-only
python -X utf8 edge_cases/run_checks.py --context
python -X utf8 edge_cases/run_checks.py --heavy-deletion
python -X utf8 edge_cases/run_checks.py --deletion-benchmark
```

Các ca có ngữ cảnh dùng quan hệ được cung cấp riêng trong tệp kiểm thử để kiểm tra bộ xếp hạng. Notebook và bản Python không nạp các tệp kiểm thử khi chấm bài.

Khi đã nhận ra tỉnh/thành, Solution dùng quan hệ hành chính của Cẩm Lệ, Cửa Lò và Chí Linh để phân biệt các ứng viên viết tắt CL. Với tên phường ngắn có tiền tố rõ ràng, Solution có thể bỏ hai ký tự thừa nếu tra được tên hợp lệ, như Cwam Lwe thành Cẩm Lệ.

## Kết quả

| Kiểm thử | Kết quả |
|---|---:|
| Public gốc | 600/600 trường (10/10) |
| Ca theo yêu cầu đề | 33/33 |
| Ca viết tay | 47/47 |
| Ca có ngữ cảnh được cung cấp trong kiểm thử | 26/26 |
| Ca xếp hạng tổ hợp | 5/5 |
| Ca biên thiếu ký tự | 10/10 |

Phép thử nhiễu xóa tối đa 60% chữ cái trong tên, giữ nguyên số và dùng seed cố định. Mỗi nhóm tạo 200 biến thể từ public.

| Thành phần bị xóa ký tự | Đúng cả địa chỉ | Đúng từng trường |
|---|---:|---:|
| Tên đường | 136/200 | 536/600 |
| Phường/xã | 136/200 | 536/600 |
| Tỉnh/thành | 166/200 | 566/600 |
| Cả ba trường | 74/200 | 432/600 |

Điểm trên tập ẩn chưa biết.

So sánh với bản DP duyệt danh sách tên, Trie + DP cho cùng kết quả trên public, 800 biến thể xóa ký tự và 2.136 biến thể khác. Thời gian xử lý trung vị qua 8 lượt trên 800 biến thể xóa ký tự giảm từ 723,8 ms xuống 609,7 ms, khoảng 16%. Chi phí khởi tạo trung vị qua 20 lượt tăng từ 57,9 ms lên 61,4 ms.
