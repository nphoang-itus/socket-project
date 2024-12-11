import socket
import threading
import os
import json
import signal
import time

# Cấu hình mạng
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 65432
CHUNK_SIZE = 1024 # 1KB
directory = "files"  # Thư mục chứa file
char_encoding = "utf-8"  # Bộ mã hóa ký tự

def scan_files_for_server():
    """
    Quét tất cả các file trong thư mục hiện tại, tính kích thước,
    lưu vào `data.txt` và trả về thông tin file dưới dạng dictionary.
    """
    if not os.path.exists(directory):
        print(f"Lỗi: Thư mục '{directory}' không tồn tại.")
        exit(1)  # Exit the program if the directory does not exist
    
    if not os.access(directory, os.R_OK):
        print(f"Lỗi: Không thể truy cập vào thư mục '{directory}'.")
        exit(1)  # Exit the program if the directory is not accessible
    
    file_data = {}
    with open("data.txt", "w") as data_file:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                size_bytes = os.path.getsize(file_path)
                size_readable = convert_size(size_bytes)
                file_data[filename] = size_bytes
                data_file.write(f"{filename} {size_readable}\n")
    return file_data

def convert_size(size_bytes):
    """
    Chuyển đổi kích thước file từ bytes sang KB, MB, hoặc GB phù hợp.
    """
    if size_bytes >= 1024 ** 5:
        return f"{size_bytes / (1024 ** 5):.2f}PB"
    elif size_bytes >= 1024 ** 4:
        return f"{size_bytes / (1024 ** 4):.2f}TB"
    elif size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f}GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.2f}MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f}KB"
    else:
        return f"{size_bytes}B"

class Server:
    """
    Server xử lý đa luồng cho phép client tải file theo từng chunk.
    """
    def __init__(self):
        self.file_datas = scan_files_for_server()    # Lưu thông tin file trên server
        self.is_running = True   # Biến kiểm tra server đang hoạt động hay không
        self.clients = set()  # Lưu thông tin client kết nối đến server
        self.server_socket = None  # Socket server
        signal.signal(signal.SIGINT, self.handle_shutdown) # Xử lý tắt server khi nhận tín hiệu SIGINT
    
    def handle_shutdown(self, signum, frame):
        """
        Xử lý tắt server khi nhận tín hiệu SIGINT - Ctrl + C.
        """
        print("Server is shutting down...")
        self.is_running = False

        # Đóng tất cả kết nối đến client
        for client in self.clients.copy():
            try:
                client.close()
            except:
                pass

        # Đóng server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
    
    def handle_clients(self, client_connect, client_address):
        """
        Xử lý client kết nối đến server.
        """
        self.clients.add(client_connect)
        print(f"New connection from {client_address}")

        try:
            # Gửi thông tin file trên server đến client
            json_data = json.dumps(self.file_datas).encode(char_encoding)
            client_connect.sendall(json_data)

            while self.is_running:
                # Nhận yêu cầu tải file từ client (format: filename|offset|size)
                request = client_connect.recv(1024).decode(char_encoding)
                if not request:
                    break

                # Xử lý yêu cầu tải file từ client
                if "|" in request:
                    filename, offset, size = request.split("|")
                    offset, size = int(offset), int(size)

                    if filename in self.file_datas:
                        file_path = os.path.join(directory, filename)

                        if os.path.exists(file_path) and os.path.isfile(file_path):
                            with open(file_path, "rb") as file:
                                file.seek(offset)
                                chunk_data = file.read(size)
                                client_connect.sendall(chunk_data)
                        
                        else:
                            client_connect.sendall(b"ERROR: File not found on server!")

        except Exception as e:
            print(f"Error: {e}")

        finally:
            self.clients.remove(client_connect)
            client_connect.close()
            print(f"Connection from {client_address} closed")

    def start(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            self.server_socket = server
            server.bind((SERVER_HOST, SERVER_PORT))
            server.listen()
            print(f"Server is listening on {SERVER_HOST}:{SERVER_PORT}")

            while self.is_running:
                loads = 1
                loads += 1
                try:
                    client_connect, client_address = server.accept()
                    
                    if self.is_running:
                        client_thread = threading.Thread(target=self.handle_clients, args=(client_connect, client_address), daemon=True)
                        client_thread.daemon = True
                        client_thread.start()
                except KeyboardInterrupt:
                    self.handle_shutdown(signal.SIGINT, None)
                    break
                except:
                    if self.is_running:
                        print("Error: Failed to accept client connection")


if __name__ == '__main__':
    server = Server()
    server.start() # Khởi động server