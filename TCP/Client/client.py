# client.py
import socket
import json
import os
import time
import threading

# Network configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 2049
CHUNK_SIZE = 1024 * 1024

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

class FileClient:
    """
    Client tải file từ server theo từng chunk.
    """
    def __init__(self):
        self.server_files = {}         # Danh sách file từ server
        self.downloaded_files = set() # File đã tải xong
        self.is_running = True
        self.progress = {}
        self.print_lock = threading.Lock()

    def connect_to_server(self):
        """
        Kết nối tới server và lấy danh sách file.
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((SERVER_HOST, SERVER_PORT))
            file_metadata = self.socket.recv(4096).decode("utf-8")
            self.server_files = json.loads(file_metadata)

            print("Available files on the server:")
            for filename, size in self.server_files.items():
                size_readable = convert_size(size)
                print(f"{filename}: {size_readable}")
        except Exception as e:
            print(f"Error connecting to server: {e}")
            self.is_running = False

    def monitor_input(self):
        """
        Theo dõi file input.txt để tải file mới.
        """
        print("Monitoring input.txt for download requests...")
        try:
            while self.is_running:
                if not os.path.exists("input.txt"):
                    print("Lỗi: File 'input.txt' không tồn tại.")
                    exit(1)  # Exit the program if the input file does not exist

                if os.path.exists("input.txt"):
                    with open("input.txt", "r") as input_file:
                        files_to_download = input_file.read().splitlines()

                    for filename in files_to_download:
                        if filename not in self.downloaded_files:
                            self.download_file(filename)
                            self.downloaded_files.add(filename)
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nClient is shutting down...")
            self.is_running = False
        except Exception as e:
            print(f"Error monitoring input file: {e}")
        finally:
            self.is_running = False

    def download_file(self, filename):
        """
        Tải file từ server theo từng chunk.
        """
        if filename not in self.server_files:
            print(f"Error: {filename} does not exist on the server.")
            return

        file_size = self.server_files[filename]
        chunk_size = file_size // 4
        threads = []

        for i in range(4):
            offset = i * chunk_size
            part_size = chunk_size if i < 3 else file_size - offset
            thread = threading.Thread(target=self.download_chunk, args=(filename, offset, part_size, i))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self.merge_chunks(filename)

    def update_progress(self, filename, chunk_id, progress):
        """Update download progress display for all chunks"""
        with self.print_lock:
            self.progress[f"{filename}_part{chunk_id}"] = progress
            
            # Handle initial display setup
            if chunk_id == 0 and progress == 0:
                print('\n' * 4)
            else:
                print('\033[4F', end='')  # Move cursor up 4 lines
                
            # Update all progress lines
            for i in range(4):
                prog = self.progress.get(f"{filename}_part{i}", 0)
                print(f"\033[K{filename} part {i+1}.... {prog:.0f}%")

    def download_chunk(self, filename, offset, size, part_number):
        """
        Tải một phần (chunk) của file.
        """
        try:
            chunk_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            chunk_socket.connect((SERVER_HOST, SERVER_PORT))
            chunk_socket.recv(4096)  # Bỏ qua danh sách file ban đầu

            chunk_socket.sendall(f"{filename}:{offset}:{size}".encode("utf-8"))
            chunk_data = b""
            total_received = 0
            while len(chunk_data) < size:
                packet = chunk_socket.recv(min(CHUNK_SIZE, size - len(chunk_data)))
                if not packet:
                    break
                chunk_data += packet
                total_received += len(packet)
                progress = (total_received / size) * 100
                self.update_progress(filename, part_number, progress)

            part_filename = os.path.join("Downloads", f"{filename}.part{part_number}")
            os.makedirs(os.path.dirname(part_filename), exist_ok=True)
            with open(part_filename, "wb") as part_file:
                part_file.write(chunk_data)
            print(f"Finished chunk {part_number + 1} of {filename}")
        except Exception as e:
            print(f"Error downloading chunk {part_number + 1} of {filename}: {e}")
        finally:
            chunk_socket.close()

    def merge_chunks(self, filename):
        """
        Gộp các chunk thành file hoàn chỉnh.
        """
        final_filename = os.path.join("downloads", filename)
        with open(final_filename, "wb") as final_file:
            for part_number in range(4):
                part_filename = os.path.join("downloads", f"{filename}.part{part_number}")
                with open(part_filename, "rb") as part_file:
                    final_file.write(part_file.read())
                os.remove(part_filename)
        print(f"File {filename} has been merged.")

    def start_client(self):
        """
        Khởi động client.
        """
        self.connect_to_server()
        self.monitor_input()


if __name__ == "__main__":
    client = FileClient()
    client.start_client()