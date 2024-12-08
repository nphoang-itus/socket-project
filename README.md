# socket
The project on sockets for the Computer Networks course, semester 1 of the 2024-2025 academic year: Downloading files from the server.

# idea
A. Server
1. Tạo 1 file files.txt lưu các tên file có trên server với định dạng [NAME_FILE] [SIZE_FILE]MB. VD: File1.zip 12MB.
2. Làm 1 hàm load_file lên server: Bản chất hàm này là sẽ tạo 1 dict (từ điển) để đọc vào 2 trường dữ liệu (key - value) và trả về dict đó. Giả sử hàm này trả về
3. Tạo hàm xử lý socket với 1 client (Coi như đã hand shaking với client):
**Bước 1:** Tạo 1 list file_entries để lưu lại danh sách các file cho phép client download về (giả sử đã sử dụng hàm load_file để lưu danh sách vào dict files). Đọc từng trường trong files, nối từng key - value thành cấu trúc string kiểu [NAME_FILE] [SIZE_FILE]MB và gửi cho client.
**Bước 2** (Tại bước này, hãy qua bên Client đọc để hiểu):

B.Client
1. Tạo 1 hàm get_file_list để lấy danh sách các file mà server cho phép down về.
2. Tạo hàm download_file: Hand shaking với server, sau đó nhận thông tin các file mà server cho download bằng hàm get_file_list (lưu ở dạng string, các ký tự \n trong tương ứng với xuống hàng).
3. 