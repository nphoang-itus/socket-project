import socket
import threading
import os
import json
import signal
import time
import ipaddress
import sys
import struct

# Cấu hình mạng
SERVER_HOST = None
SERVER_PORT = None
CHUNK_SIZE = 5 * 1024 * 1024 #5MB
DOWNLOAD_DIR = "downloads"
PART_STORAGE = "bin"
CHAR_ENCODING = "utf-8"  # Bộ mã hóa ký tự
INPUT_TXT = "input.txt"
dot_progress = 0

def get_server_ip():
    """
    Nhập IP server từ người dùng.
    """
    while True:
        try:
            ip = input("Nhập IP server: ")
            if ipaddress.ip_address(ip):
                return ip
            else:
                print("IP không hợp lệ.")
        except ValueError:
            print("IP không hợp lệ.")
        except KeyboardInterrupt:
            sys.exit(1)

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
        except KeyboardInterrupt:
            sys.exit(1)

def format_size_file(size_bytes):
    """
    Chuyển đổi kích thước file từ bytes sang KB, MB, hoặc GB phù hợp.
    """
    if size_bytes >= 1024 ** 4:
        return f"{size_bytes / (1024 ** 4):.2f}TB"
    elif size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f}GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.2f}MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f}KB"
    else:
        return f"{size_bytes}B"
    
def scan_downloaded_files():
    """
    Quét tất cả các file trong thư mục downloads để kiểm tra file đã tải xong.
    """
    downloaded_files = set()
    if not os.path.exists(DOWNLOAD_DIR):
        print(f"Lỗi: Thư mục '{DOWNLOAD_DIR}' không tồn tại.")
        sys.exit(1)  # Exit the program if the directory does not exist
    
    if not os.access(DOWNLOAD_DIR, os.R_OK):
        print(f"Lỗi: Không thể truy cập vào thư mục '{DOWNLOAD_DIR}'.")
        sys.exit(1)  # Exit the program if the directory is not accessible
    
    for filename in os.listdir(DOWNLOAD_DIR):
        file_path = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.isfile(file_path):
            downloaded_files.add(filename)
    return downloaded_files

class Client:
    """
    Client tải file từ server theo từng chunk.
    """
    def __init__(self):
        self.server_files = {}       # Danh sách file từ server
        self.downloaded_files = scan_downloaded_files() # File đã tải xong
        self.is_connected = True
        self.progress = {}
        self.client_socket = None
        self.print_lock = threading.Lock()
        signal.signal(signal.SIGINT, self.handle_breaking)

    def handle_breaking(self, signum, frame):
        """
        Xử lý tín hiệu Ctrl C từ bàn phím.
        """
        print("\033[J", end='')
        print(f"Dicconnecting...")
        self.is_connected = False
        if self.client_socket:
            self.client_socket.close()
    
    def connect_to_server(self):
        """
        Kết nối đến server.
        """
        global SERVER_HOST, SERVER_PORT
        try:
            # Tạo socket nếu chưa tồn tại
            if not self.client_socket:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.client_socket.connect((SERVER_HOST, SERVER_PORT))
                self.client_socket.settimeout(5)
                print("Connected to server.")

                # Nhận danh sách file từ server
                header = self.client_socket.recv(8)
                if not header:
                    return False
                    
                # Giải mã độ dài từ header
                data_length = struct.unpack(">Q", header)[0]
                
                # Nhận toàn bộ dữ liệu dựa trên độ dài đã giải mã
                self.server_files = json.loads(self.client_socket.recv(data_length).decode(CHAR_ENCODING))
                self.print_available_files()
            
            # Kết nối thành công và không có ngoại lệ
            # Hoặc đã có socket rồi
            return True 
        except Exception as e:
            print(f"Error connecting to server: {e}")
            if self.client_socket:
                self.client_socket.close()
                self.client_socket = None
                
            # Cho phép người dùng nhập lại IP/PORT
            SERVER_HOST = get_server_ip()
            SERVER_PORT = get_server_port()
            return False

        
    def print_available_files(self):
        """
        In danh sách file có sẵn trên server.
        """
        print(f"{'-' * 30}")
        print("Available files on the server:")
        for filename, size in self.server_files.items():
            size_readable = format_size_file(size)
            print(f"{filename}: {size_readable}")
        print(f"{'-' * 30}" + "\n")
    
    def monitor_input(self):
        """
        Theo dõi file input.txt để tải file mới.
        """
        global dot_progress
        dot_progress += 1 if dot_progress < 3 else -3
        print("\033[J", end='')
        print("Monitoring input.txt for download requests" + '.' * dot_progress)

        try:
            if not os.path.exists(INPUT_TXT):
                print("ERROR: File 'input.txt' not found!")
                return []
            
            with open(INPUT_TXT, 'r') as input_file:
                files_to_download = input_file.read().strip().split("\n")

            new_files_to_download = [f for f in files_to_download 
                                        if f in self.server_files 
                                        and f not in self.downloaded_files]
            
            invalid_files = [f for f in files_to_download
                                if f not in self.server_files]
            
            if new_files_to_download:
                print('-' * 30 + "\nNew files to download:")
                for filename in new_files_to_download:
                    print(filename)
                print('-' * 30)
            else:
                print('-' * 30 + "\nFiles not found on the server:")
                for filename in invalid_files:
                    print(filename)
                print("No new files to download!\n" + '-' * 30)
                print(f"\033[{len(invalid_files) + 5}F", end='')
            return new_files_to_download
        except Exception as e:
            print(f"Error monitoring input.txt: {e}")
            return []
        
    def print_progress(self, filename, chunk_id, progress_percent):
        """
        In tiến trình tải file.
        """
        with self.print_lock:
            self.progress[f"{filename}_part_{chunk_id}"] = progress_percent
            
            # Xử lý in thông tin tiến trình đầu tiên
            if chunk_id == 0 and progress_percent == 0:
                print('\n' * 4)
            else:
                print('\033[4F', end='')
                
          # In tiến trình tải file
            for i in range(4):
                progress_display = self.progress.get(f"{filename}_part_{i}", 0)
                bar_length = 20  # Độ dài của thanh tiến trình
                filled_length = int(bar_length * progress_display // 100)
                bar = '█' * filled_length + ' ' * (bar_length - filled_length)
                print(f"\033[K{filename} - Part {i+1} {bar} {progress_display:.0f}%")
    
    def download_part_file(self, filename, offset, part_size, part_number):
        """
        Tải một phần của file.
        """
        part_file_socket = None
        retry_count = 0
        while retry_count < 3:
            try:
                part_file_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                part_file_socket.connect((SERVER_HOST, SERVER_PORT))
                part_file_socket.settimeout(5)
                
                # Bỏ qua danh sách file ban đầu
                header = part_file_socket.recv(8)

                if not header:
                    print("Connection lost")
                    continue
              
                # Bỏ qua dữ liệu từ server
                data_length = struct.unpack(">Q", header)[0]
                part_file_socket.recv(data_length).decode(CHAR_ENCODING)

                # Gửi yêu cầu tải file đến server

                # # HOÀNG LÀM:
                message = f"{filename}|{offset}|{part_size}".encode(CHAR_ENCODING)
                size_message_header = struct.pack(">Q", len(message))
                # part_file_socket.sendall(size_message)
                # ###

                part_file_socket.sendall((size_message_header + message))
                part_file_buffer = b''  # Lưu trữ dữ liệu tạm thời
                
                total_received = 0   # Tổng số byte nhận được
                while total_received < part_size:
                    remaining_in_buffer = part_size - total_received
                    chunk_packet = part_file_socket.recv(min(remaining_in_buffer, CHUNK_SIZE))
                    
                    if not chunk_packet:
                        raise ConnectionError("Connection lost")
                    
                    # Kiểm tra thông báo lỗi từ server
                    if b"ERROR: File not found on server!" in chunk_packet:
                        print("Error: File not found on server!")
                        return False
                    
                    # Thêm dữ liệu vào buffer
                    part_file_buffer += chunk_packet
                    total_received += len(chunk_packet)
                    self.print_progress(filename, part_number, ((total_received / part_size) * 100))

                # Sau khi nhận đủ part_size, ghi dữ liệu vào file
                part_filename = os.path.join(PART_STORAGE, f"{filename}.part{part_number}")
                os.makedirs(os.path.dirname(part_filename), exist_ok=True)
                with open(part_filename, "wb") as part_file:
                    part_file.write(part_file_buffer)
                    part_file.flush()
                    os.fsync(part_file.fileno())
                return True

            except Exception as e:
                print(f"Error downloading chunk {part_number + 1} of {filename}: {e}")
                retry_count += 1
                return False
            finally:
                if part_file_socket:
                    header = struct.pack(">Q", len(b"CLOSE PART SOCKET")) 
                    part_file_socket.sendall(header + b"CLOSE PART SOCKET")
                    part_file_socket.close()
                    part_file_socket = None
        
        print(f"Failed to download chunk {part_number + 1} of {filename} after {3} attempts.")
        return False

    def merge_chunks(self, filename):
        """
        Gộp các chunk thành file hoàn chỉnh.
        """
        final_filename = os.path.join(DOWNLOAD_DIR, filename)
        with open(final_filename, "wb") as final_file:
            for part_number in range(4):
                part_filename = os.path.join(PART_STORAGE, f"{filename}.part{part_number}")
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
            part_size = file_size // 4

            print('\n' * 4)

            # Tạo 4 thread để tải file
            threads = []
            results = [None] * 4
            
            def thread_target(index, *args):
                """
                Hàm hỗ trợ kiểm tra kết quả của từng thread.
                """
                results[index] = self.download_part_file(*args)

            for i in range(4):
                offset = i * part_size
                part_size = part_size if i < 3 else file_size - offset
                thread = threading.Thread(target=thread_target, args=(i, filename, offset, part_size, i), daemon=True)
                thread.daemon = True
                thread.start()
                threads.append(thread)

            for thread in threads:
                thread.join()

             # Kiểm tra kết quả của từng thread
            if not all(results):
                print(f"Error downloading file {filename}: One or more chunks failed to download.")
                return False

            self.merge_chunks(filename)
            self.downloaded_files.add(filename)
            print(f"\nFile {filename} has been downloaded.\n")
            return True
        
        except Exception as e:
            print(f"Error downloading file {filename}: {e}")
            self.cleanup_chunks(filename)
            return False
        
    def cleanup_chunks(self, filename):
        """
        Xóa các phần chunk của file.
        """
        for part_number in range(4):
            part_filename = os.path.join(PART_STORAGE, f"{filename}.part{part_number}")
            if os.path.exists(part_filename):
                os.remove(part_filename)

    def start(self):
        while self.is_connected:
            try:
                if not self.connect_to_server():
                    print("Trying to reconnect in 5 seconds...\n")
                    time.sleep(5)
                    continue

                new_files_to_download = self.monitor_input()
                for filename in new_files_to_download:
                    if self.is_connected:
                        if not self.download_file(filename):
                            print(f"Error downloading {filename}")
                
                time.sleep(5)
            except KeyboardInterrupt:
                self.handle_breaking(signal.SIGINT, None)
                break
            except Exception as e:
                print(f"Error: {e}")
            finally:
                if self.is_connected and self.client_socket:
                    try:
                        message = self.client_socket.recv(15).decode(CHAR_ENCODING)
                        if "SERVER_SHUTDOWN" in message:
                            print("\33[JServer has shut down. Disconnecting...")
                            self.handle_breaking(signal.SIGINT, None)
                            break
                    except socket.timeout:
                        pass
                    except Exception as e:
                        print(f"Error receiving server shutdown message: {e}")
                        self.is_connected = False
                        self.client_socket.close()
        print("\33[JShut down...")

if __name__ == "__main__":
    SERVER_HOST = get_server_ip()
    SERVER_PORT = get_server_port()
    client = Client()
    client.start()