# server.py
import socket
import threading
import os
import json
import signal

# Network configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 2049
CHUNK_SIZE = 1024 * 1024  # 256KB per chunk
directory = "File_onServer"


def scan_server_files():
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
    with open("files.txt", "w") as data_file:
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
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f}GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.2f}MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f}KB"
    else:
        return f"{size_bytes}B"


class FileServer:
    """
    Server xử lý đa luồng cho phép client tải file theo từng chunk.
    """
    def __init__(self):
        self.file_metadata = scan_server_files()  # Đọc thông tin file trên server
        self.is_running = True                    # Trạng thái server

    def handle_client(self, conn, addr):
        """
        Xử lý yêu cầu từ một client.
        """
        print(f"Client connected from {addr}")
        try:
            # Send file list to client
            conn.sendall(json.dumps(self.file_metadata).encode("utf-8"))

            while self.is_running:
                # Receive file download request (format: filename:offset:size)
                request = conn.recv(1024).decode("utf-8")
                if not request:
                    break

                filename, offset, size = request.split(":")
                offset, size = int(offset), int(size)

                if filename in self.file_metadata:
                    file_path = os.path.join(directory, filename)
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as file:
                            file.seek(offset)
                            chunk_data = file.read(size)
                            conn.sendall(chunk_data)
                    else:
                        conn.sendall(b"ERROR: File does not exist.")
                else:
                    conn.sendall(b"ERROR: File does not exist.")
        except Exception as e:
            print(f"Error with client {addr}: {e}")
        finally:
            conn.close()
            print(f"Client from {addr} has disconnected.")

    def start_server(self):
        """
        Khởi động server.
        """
        signal.signal(signal.SIGINT, self.shutdown_server)
        print(f"Server is running on {SERVER_HOST}:{SERVER_PORT}")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.bind((SERVER_HOST, SERVER_PORT))
            server_socket.listen(5)

            while self.is_running:
                conn, addr = server_socket.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

    def shutdown_server(self, signum, frame):
        """
        Đóng server khi nhận tín hiệu Ctrl+C.
        """
        print("\nShutting down the server...")
        self.is_running = False
        os._exit(0)  # Exit the program immediately


if __name__ == "__main__":
    server = FileServer()
    server.start_server()
