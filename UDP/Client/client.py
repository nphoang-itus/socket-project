import socket
import time
import os
import logging
import signal
import json
import sys
import threading
import struct

HOST = "0.0.0.0"
PORT = 6264
MAX_BYTES_RECV = 4096
BUFFER = 1024
CHAR_ENCODING = "utf_8"
INPUT_TXT = "input.txt"
DIR_DOWNLOADED = "Downloaded"

dot_progress = 0

logging.basicConfig(
    filename = "client.log",
    level = logging.INFO,
    format = "%(asctime)s || %(levelname)s || %(message)s",
    filemode = 'w'
)

class Client:
    def __init__(self):
        self.server_addr = (HOST, PORT)
        self.available_files = {}
        self.downloaded_files = set()
        self.is_running = True
        self.progress = {}
        self.client_socket = None
        self.print_lock = threading.Lock()
        signal.signal(signal.SIGINT, self.handle_shutdown)
    
    def handle_shutdown(self, signum, frame):
        logging.error("[handle_shutdown] Shutdown client.")
        print("Server is shutting down...")
        self.is_running = False

        if self.client_socket:
            try:
                self.client_socket.close()
                self.client_socket = None
            except Exception as e:
                logging.error(f"[handle_shutdown] Error closing client: {e}. Byebye!!!")
                pass

    def format_size(self, size_bytes):
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

    def print_available_files(self):
        print("Available files on the server:")
        for file_name, size_bytes in self.available_files.items():
            size_readable = self.format_size(size_bytes)
            print(f"{file_name}: {size_readable}")
        print(f"{'-' * 30}\n\n")

    def get_file_list(self):
        try:
            # Chưa mần Trường hợp giả dụ khởi tạo được socket nhưng gửi hoặc nhận lỗi -> phải gửi hoặc nhận lại
            if not self.client_socket:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.client_socket.sendto("GET_FILE_LIST".encode(CHAR_ENCODING), self.server_addr)
                logging.info("[get_file_list] Sent GET_FILE_LIST request to server.")
                data, _ = self.client_socket.recvfrom(MAX_BYTES_RECV) # _ là bỏ qua address server
                self.available_files = json.loads(data.decode(CHAR_ENCODING))
                self.print_available_files()
            return True # Chưa có socket thì khởi tạo, nếu có tức đã khởi tạo
        except Exception as e:
            logging.error(f"[get_file_list] {e}")
            print(f"Error: {e}")
            if self.client_socket:
                self.client_socket.close()
                self.client_socket = None
            return False

    def monitor_input(self):
        global dot_progress
        dot_progress += 1 if dot_progress < 3 else -3

        print('\n\033[3F', end='')
        print("\033[KMonitoring input.txt for download requests" + '.' * dot_progress)

        try:
            with open(INPUT_TXT, 'r') as inFile:
                content = inFile.read().strip()
                if not content:
                    logging.warning("[monitor_input] input.txt is empty.")
                    print(f"Warning {INPUT_TXT} is empty!")
                    return []

            files = content.split('\n')

            new_files = []
            for item in files:
                if item not in self.available_files:
                    logging.warning(f"[monitor_input] File {item} does not exist on the server!")
                    print(f"File {item} does not exist on the server!")
                    continue
                if item not in self.downloaded_files:
                    new_files.append(item)

            if new_files:
                print("New files to download:", new_files)
                logging.info(f"[monitor_input] New files to download: {new_files}")

            return new_files
        except Exception as e: # Sẽ out chương trình do ko mở được input.txt
            print(f"Error: {e}")
            logging.error(f"[monitor_input] Error: {e}")
            self.client_socket.close()
            self.client_socket = None
            sys.exit(1)

    def print_progress(self, file_name, part_number, progress_percent):
        with self.print_lock:
            self.progress[f"{file_name}_chunk_{part_number}"] = progress_percent
            
            # Xử lý in thông tin tiến trình đầu tiên
            if part_number == 0 and progress_percent == 0:
                print('\n' * 4)
            else:
                print('\033[4F', end='')
                
          # In tiến trình tải file
            for i in range(4):
                progress_display = self.progress.get(f"{file_name}_chunk_{i}", 0)
                bar_length = 20  # Độ dài của thanh tiến trình
                filled_length = int(bar_length * progress_display // 100)
                bar = '█' * filled_length + ' ' * (bar_length - filled_length)
                print(f"\033[K{file_name} - Chunk {i+1} {bar} {progress_display:.0f}%")

    def download_chunk(self, file_name, offset_chunk, size_chunk, part_number):
        chunk_socket = None
        received_packets = set()

        try:
            chunk_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            chunk_socket.settimeout(5)  # Giảm timeout xuống hợp lý hơn
            request = f"GET_CHUNK|{file_name}|{offset_chunk}|{size_chunk}|{part_number}".encode(CHAR_ENCODING)
            
            chunk_socket.sendto(request, self.server_addr)
            logging.info(f"[download_chunk] Sent GET_CHUNK request for {file_name}, part {part_number}")

            seq_check = 0
            total_received = b""
            while len(total_received) < size_chunk and self.is_running:
                try:
                    data_recv, _ = chunk_socket.recvfrom(MAX_BYTES_RECV)
                    part_recv, seq_recv, checksum, buffer_chunk = struct.unpack(
                        f"!I I B {len(data_recv) - 9}s", data_recv
                    )
                    computed_checksum = sum(buffer_chunk) % 256
                    packet_id = (part_recv, seq_recv)

                    if packet_id in received_packets:
                        logging.info(f"[download_chunk] Duplicate packet {packet_id} received, discarding.")
                        continue

                    if part_recv == part_number and seq_recv == seq_check and checksum == computed_checksum:
                        logging.info(f"[download_chunk] Valid packet {packet_id} received.")
                        ack_message = f"ACK-{part_number}_{seq_check}".encode(CHAR_ENCODING)
                        chunk_socket.sendto(ack_message, self.server_addr)
                        total_received += buffer_chunk
                        seq_check += 1
                        self.print_progress(file_name, part_number, (len(total_received) / size_chunk) * 100)
                        received_packets.add(packet_id)
                    else:
                        logging.warning(f"[download_chunk] Packet {packet_id} invalid, sending NAK.")
                        nak_message = f"NAK-{part_number}_{seq_check}".encode(CHAR_ENCODING)
                        chunk_socket.sendto(nak_message, self.server_addr)
                except socket.timeout:
                    logging.warning(f"[download_chunk] Timeout for packet {seq_check}, retrying.")
                    nak_message = f"NAK-{part_number}_{seq_check}".encode(CHAR_ENCODING)
                    chunk_socket.sendto(nak_message, self.server_addr)
        except Exception as e:
            logging.error(f"[download_chunk] Error: {e}")
        finally:
            if chunk_socket:
                chunk_socket.close()


    def merge_chunk(self, file_name):
        with open(os.path.join(DIR_DOWNLOADED, file_name), "wb") as outFile:
            for part_number in range(4):
                part_file = os.path.join(DIR_DOWNLOADED, f"{file_name}.part{part_number}")
                with open(part_file, "rb") as inFile:
                    outFile.write(inFile.read())
                os.remove(part_file)
        
        print(f"Successfully merged {file_name}.")
        logging.info(f"Successfully merged {file_name}.")

    def download_file(self, file_name):
        if file_name in self.downloaded_files:
            print(f"Error: {file_name} does not exist on the server.")
            logging.error(f"[download_file] Error: {file_name} does not exist on the server.")
            return
        
        if file_name not in self.available_files:
            logging.error(f"[download_file] Error: {file_name} does not exist on the server.")
            print(f"Error: {file_name} does not exist on the server.")
            return

        try:
            print(f"\nDownloading file {file_name} ...")

            file_size = self.available_files[file_name]
            chunk_size = file_size // 4

            threads = []
            for i in range(4):
                offset_chunk = i * chunk_size
                part_size = chunk_size if i < 3 else file_size - offset_chunk
                thread = threading.Thread(target=self.download_chunk, args=(file_name, offset_chunk, part_size, i))
                thread.daemon = True
                thread.start()
                threads.append(thread)
            
            for thread in threads:
                thread.join()

            if self.is_running:
                self.merge_chunk(file_name)
                self.downloaded_files.add(file_name)
                print(f"File {file_name} has been downloaded.\n")
                logging.info(f"[download_file] File {file_name} has been downloaded.\n")
        except Exception as e:
            print(f"Error: {e}")
            logging.error(f"Error: {e}")

    def start_client(self):
        while self.is_running:
            try:
                if not self.get_file_list():
                    print("Trying to reconnect in 5 seconds...\n")
                    time.sleep(5)
                    continue
                
                new_files_to_download = self.monitor_input()
                for file in new_files_to_download:
                    if self.is_running:
                        self.download_file(file)

                time.sleep(5)
            except KeyboardInterrupt:
                self.handle_shutdown(signal.SIGINT, None)
                break
            except Exception as e:
                print(f"Error: {e}")
                logging.error(f"Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    client = Client()
    client.start_client()