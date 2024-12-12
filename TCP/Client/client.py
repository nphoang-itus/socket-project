import socket
import threading
import os
import json
import signal
import time

# Cấu hình mạng
SERVER_HOST = "127.0.0.1"
SERVER_PORT = None
CHUNK_SIZE = 1024 * 1024
DOWNLOAD_DIR = "downloads"
CHUNK_STORAGE = "bin"
char_encoding = "utf-8"  # Bộ mã hóa ký tự
dot_progress = 0

def get_server_port():
    """
    Nhập cổng server từ người dùng.
    """
    while True:
        try:
            port = int(input("Nhập cổng server: "))
            if 1024 <= port <= 65535:
                return port
            else:
                print("Cổng phải nằm trong khoảng từ 1024 đến 65535.")
        except ValueError:
            print("Cổng không hợp lệ.")

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

class Client:
    """
    Client tải file từ server theo từng chunk.
    """
    def __init__(self):
        self.server_files = {}       # Danh sách file từ server
        self.downloaded_files = set() # File đã tải xong
        self.is_running = True
        self.progress = {}
        self.client_socket = None
        self.print_lock = threading.Lock()
        signal.signal(signal.SIGINT, self.handle_breaking)

    def handle_breaking(self, signum, frame):
        print(f"Dicconnecting...")
        self.is_running = False
        if self.client_socket:
            self.client_socket.close()
    
    def connect_to_server(self):
        """
        Kết nối đến server.
        """
        try:
            if not self.client_socket:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.client_socket.connect((SERVER_HOST, SERVER_PORT))
                self.client_socket.settimeout(1)
                print("Connected to server.")
                
                # Nhận danh sách file từ server
                self.server_files = json.loads(self.client_socket.recv(4096).decode(char_encoding))
                self.print_available_files()
            return True
        except Exception as e:
            print(f"Error connecting to server: {e}")
            return False
        except:
            return False
        
    def print_available_files(self):
        print("Available files on the server:")
        for filename, size in self.server_files.items():
            size_readable = convert_size(size)
            print(f"{filename}: {size_readable}")
        print(f"{'-' * 30}\n\n")
    
    def monitor_input(self):
        """
        Theo dõi file input.txt để tải file mới.
        """
        global dot_progress
        dot_progress += 1 if dot_progress < 3 else -3

        print('\n\033[3F', end='')
        print("\033[KMonitoring input.txt for download requests" + '.' * dot_progress)

        try:
            if not os.path.exists('input.txt'):
                print("ERROR: File 'input.txt' not found!")
                return []
            
            with open('input.txt', 'r') as input_file:
                files_to_download = input_file.read().strip().split("\n")


            new_files_to_download = [f for f in files_to_download 
                        if f in self.server_files 
                        and f not in self.downloaded_files]
            
            if new_files_to_download:
                print("New files to download:")
                for filename in new_files_to_download:
                    print(filename)
            else:
                print("No new files to download.")
            return new_files_to_download
        except Exception as e:
            print(f"Error monitoring input.txt: {e}")
            return []
        
    def print_progress(self, filename, chunk_id, progress_percent):
        """
        In tiến trình tải file.
        """
        with self.print_lock:
            self.progress[f"{filename}_chunk_{chunk_id}"] = progress_percent
            
            # Xử lý in thông tin tiến trình đầu tiên
            if chunk_id == 0 and progress_percent == 0:
                print('\n' * 4)
            else:
                print('\033[4F', end='')
                
          # In tiến trình tải file
            for i in range(4):
                progress_display = self.progress.get(f"{filename}_chunk_{i}", 0)
                bar_length = 20  # Độ dài của thanh tiến trình
                filled_length = int(bar_length * progress_display // 100)
                bar = '█' * filled_length + ' ' * (bar_length - filled_length)
                print(f"\033[K{filename} - Chunk {i+1} {bar} {progress_display:.0f}%")
    
    def download_chunk(self, filename, offset, chunk_size, part_number):
        """
        Tải một phần (chunk) của file.
        """
        chunk_socket = None
        try:
            chunk_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            chunk_socket.settimeout(20)
            chunk_socket.connect((SERVER_HOST, SERVER_PORT))
            
            # Bỏ qua danh sách file ban đầu
            chunk_socket.recv(4096).decode(char_encoding)

            # Gửi yêu cầu tải file đến server
            chunk_socket.sendall(f"{filename}|{offset}|{chunk_size}".encode(char_encoding))
            chunk_buffer = b''  # Lưu trữ dữ liệu tạm thời
            
            total_received = 0   # Tổng số byte nhận được
            while total_received < chunk_size:
                remaining = chunk_size - total_received
                packet = chunk_socket.recv(min(remaining, CHUNK_SIZE))
                
                if not packet:
                    raise ConnectionError("Connection lost")
                
                # Thêm dữ liệu vào buffer
                chunk_buffer += packet
                total_received += len(packet)
                self.print_progress(filename, part_number, ((total_received / chunk_size) * 100))

            # Sau khi nhận đủ chunk_size, ghi dữ liệu vào file
            part_filename = os.path.join(CHUNK_STORAGE, f"{filename}.chunk{part_number}")
            os.makedirs(os.path.dirname(part_filename), exist_ok=True)
            with open(part_filename, "wb") as part_file:
                part_file.write(chunk_buffer)

        except Exception as e:
            print(f"Error downloading chunk {part_number + 1} of {filename}: {e}")
        finally:
            if chunk_socket:
                chunk_socket.close()

    def merge_chunks(self, filename):
        """
        Gộp các chunk thành file hoàn chỉnh.
        """
        final_filename = os.path.join(DOWNLOAD_DIR, filename)
        with open(final_filename, "wb") as final_file:
            for part_number in range(4):
                part_filename = os.path.join(CHUNK_STORAGE, f"{filename}.chunk{part_number}")
                with open(part_filename, "rb") as part_file:
                    final_file.write(part_file.read())
                os.remove(part_filename)

    def download_file(self, filename):
        """
        Tải file từ server theo từng chunk.
        """
        if filename in self.downloaded_files:
            return True

        if filename not in self.server_files:
            print(f"Error: {filename} does not exist on the server.")
            return False
        
        try:
            print(f"\nDownloading file {filename} ...")

            # Tính kích thước chunk file
            self.progress = {}
            file_size = self.server_files[filename]
            chunk_size = file_size // 4

            print('\n' * 4)

            # Tạo 4 thread để tải file
            threads = []
            for i in range(4):
                offset = i * chunk_size
                part_size = chunk_size if i < 3 else file_size - offset
                thread = threading.Thread(target=self.download_chunk, args=(filename, offset, part_size, i))
                thread.daemon = True
                thread.start()
                threads.append(thread)

            for thread in threads:
                thread.join()

            self.merge_chunks(filename)
            self.downloaded_files.add(filename)
            print(f"\nFile {filename} has been downloaded.\n")
            return True
        
        except Exception as e:
            print(f"Error downloading file {filename}: {e}")
            return False
        
    
    def start(self):
        while self.is_running:
            try:
                if not self.connect_to_server():
                    print("Trying to reconnect in 5 seconds...")
                    time.sleep(5)
                    continue
                
                new_files_to_download = self.monitor_input()
                for filename in new_files_to_download:
                    if self.is_running:
                        self.download_file(filename)
                
                time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(5)
        print("Client is shut down...")

if __name__ == "__main__":
    SERVER_PORT = get_server_port()
    client = Client()
    client.start() 