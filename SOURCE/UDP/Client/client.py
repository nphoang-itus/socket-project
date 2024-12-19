import socket
import time
import os
import logging
import signal
import json
import sys
import threading
import struct
import ipaddress

SERVER_HOST = None
SERVER_PORT = None
BUFFER = 8192
CHAR_ENCODING = "utf_8"
INPUT_TXT = "input.txt"
DIR_DOWNLOADED = "downloads"
dot_progress = 0

logging.basicConfig(
    filename = "client.log",
    level = logging.INFO,
    format = "%(asctime)s || %(levelname)s || %(message)s",
    filemode = 'w'
)

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

class Client:
    def __init__(self):
        self.server_addr = None
        self.available_files = {}
        self.downloaded_files = set()
        self.is_running = True
        self.progress = {}
        self.client_socket = None
        self.print_lock = threading.Lock()
        signal.signal(signal.SIGINT, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        logging.error("[handle_shutdown] Shutdown client.")
        print("\033[J", end='')
        print(f"Dicconnecting...")
        self.is_running = False

        if self.client_socket:
            try:
                self.client_socket.close()
                self.client_socket = None
            except Exception as e:
                logging.error(f"[handle_shutdown] Error closing client: {e}. Byebye!!!")
                pass
        
        time.sleep(3)
        sys.exit(0)

    def format_file_size(self, size_bytes):
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

    def display_available_files(self):
        print(f"{'-' * 30}")
        print("Available files on the server:")
        for filename, size in self.available_files.items():
            size_readable = self.format_file_size(size)
            print(f"{filename}: {size_readable}")
        print(f"{'-' * 30}" + "\n")

    def connect_to_server(self):
        global SERVER_HOST, SERVER_PORT
        try:
            if not self.client_socket:
                self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.server_addr = (SERVER_HOST, SERVER_PORT)
                message = "GET_FILE_LIST"
                message_len = struct.pack("!I", len(message))
                self.client_socket.sendto(message_len, self.server_addr)
                self.client_socket.sendto(message.encode(CHAR_ENCODING), self.server_addr)

                logging.info("[get_file_list] Sent GET_FILE_LIST request to server.")

                len_data, _ = self.client_socket.recvfrom(4)
                len_data = struct.unpack("!I", len_data)[0]
                data, _ = self.client_socket.recvfrom(len_data) # _ là bỏ qua address server

                if data.decode(CHAR_ENCODING).startswith("ERROR"):
                    return False

                self.available_files = json.loads(data.decode(CHAR_ENCODING))
                self.display_available_files()
            return True # Chưa có socket thì khởi tạo, nếu có tức đã khởi tạo
        except Exception as e:
            logging.error(f"[get_file_list] {e}")
            print(f"Error: {e}")
            if self.client_socket:
                self.client_socket.close()
                self.client_socket = None

            SERVER_HOST = get_server_ip()
            SERVER_PORT = get_server_port()
            return False

    def monitor_input(self):
        global dot_progress
        dot_progress += 1 if dot_progress < 3 else -3

        print('\033[J', end='')
        print("Monitoring input.txt for download requests" + '.' * dot_progress)

        try:
            with open(INPUT_TXT, 'r') as inFile:
                content = inFile.read().strip()
                if not content:
                    logging.warning("[monitor_input] input.txt is empty.")
                    print(f"Warning {INPUT_TXT} is empty!")
                    return []

            files = content.split('\n')
        
            new_files_to_download = [f for f in files 
                                        if f in self.available_files 
                                        and f not in self.downloaded_files]
            
            invalid_files = [f for f in files
                                if f not in self.available_files]
            
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

    def calc_checksum(self, data):
        """
        Tính checksum cho dữ liệu nhị phân (binary data) bằng cách gộp các byte thành số 16-bit 
        và tính bù một (one's complement) của tổng.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("Dữ liệu đầu vào phải là kiểu bytes hoặc bytearray.")
        
        # Tổng ban đầu
        checksum = 0

        # Xử lý từng cặp byte
        length = len(data)
        for i in range(0, length - 1, 2):
            # Gộp hai byte thành số 16-bit (big-endian)
            word = (data[i] << 8) + data[i + 1]
            checksum += word

        # Nếu độ dài dữ liệu là lẻ, xử lý byte cuối
        if length % 2 == 1:
            checksum += data[-1] << 8  # Byte lẻ được coi là byte cao của một số 16-bit

        # Gói gọn checksum trong phạm vi 16-bit
        checksum = (checksum & 0xFFFF) + (checksum >> 16)  # Cộng dồn các bit carry
        checksum = (checksum & 0xFFFF)  # Lấy 16 bit cuối

        # Tính bù một (one's complement)
        checksum = ~checksum & 0xFFFF

        return checksum

    def download_chunk(self, file_name, offset_part, size_part, part_number):
        chunk_socket = None
        received_packets = set()
        retry_count = 0

        while retry_count < 3:
            try:
                chunk_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                logging.info(f"[download_chunk] Sent GET_CHUNK request for {file_name}, part {part_number}")
                request = f"GET_CHUNK|{file_name}|{offset_part}|{size_part}|{part_number}".encode(CHAR_ENCODING)
                chunk_socket.sendto(request, self.server_addr)

                seq_check = 0
                total_received = b""
                
                while len(total_received) < size_part and self.is_running:
                    try:
                        chunk_socket.settimeout(5)
                        remaining = size_part - len(total_received)
                        data_recv, chunk_server = chunk_socket.recvfrom(min(remaining, BUFFER) + 12)
                        part_recv, seq_recv, checksum, buffer_chunk = struct.unpack(
                            f"!I I I {len(data_recv) - 12}s", data_recv
                        )

                        if not buffer_chunk:
                            raise ConnectionError("Connection lost")

                        # computed_checksum = sum(buffer_chunk) % 256
                        computed_checksum = self.calc_checksum(buffer_chunk)
                        packet_id = (part_recv, seq_recv)

                        if packet_id in received_packets:
                            logging.info(f"[download_chunk] Duplicate packet {packet_id} received, discarding.")
                            continue
                        
                        if seq_recv == seq_check and checksum == computed_checksum:
                            logging.info(f"[download_chunk] Valid packet {packet_id} received.")
                            ack_message = f"ACK-{part_number}_{seq_check}".encode(CHAR_ENCODING)
                            chunk_socket.sendto(ack_message, chunk_server)
                            total_received += buffer_chunk
                            seq_check += 1
                            self.print_progress(file_name, part_number, (len(total_received) / size_part) * 100)
                            received_packets.add(packet_id)
                            part_file = os.path.join(DIR_DOWNLOADED, f"{file_name}.part{part_number}")
                            os.makedirs(os.path.dirname(part_file), exist_ok=True)
                            with open(part_file, "wb") as part_file:
                                part_file.write(total_received)
                                part_file.flush()
                                os.fsync(part_file.fileno())
                        else:
                            logging.warning(f"[download_chunk] Packet {packet_id} invalid, sending NAK.")
                            nak_message = f"NAK-{part_number}_{seq_check}".encode(CHAR_ENCODING)
                            chunk_socket.sendto(nak_message, chunk_server)
                            continue
                    except socket.timeout:
                        logging.warning(f"[download_chunk] Timeout for packet {part_number}_{seq_check}, retrying.")
                        nak_message = f"NAK-{part_number}_{seq_check}".encode(CHAR_ENCODING)
                        chunk_socket.sendto(nak_message, chunk_server)
                        continue
                return True
            except Exception as e:
                logging.error(f"[download_chunk] Error: {e}")
                retry_count += 1
                return False
            finally:
                if chunk_socket:
                    chunk_socket.close()
                    chunk_socket = None
        
        print(f"Failed to download chunk {part_number + 1} of {file_name} after {3} attempts.")
        return False

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
            return True
        
        if file_name not in self.available_files:
            logging.error(f"[download_file] Error: {file_name} does not exist on the server.")
            print(f"Error: {file_name} does not exist on the server.")
            return False

        try:
            print(f"\nDownloading file {file_name} ...")

            self.progress = {}
            file_size = self.available_files[file_name]
            chunk_size = file_size // 4
            
            print('\n' * 4)

            threads = []
            results = [None] * 4

            def thread_target(index, *args):
                """
                Hàm hỗ trợ kiểm tra kết quả của từng thread.
                """
                results[index] = self.download_chunk(*args)

            for i in range(4):
                offset_part = i * chunk_size
                part_size = chunk_size if i < 3 else file_size - offset_part
                thread = threading.Thread(target=thread_target, args=(i, file_name, offset_part, part_size, i))
                thread.daemon = True
                thread.start()
                threads.append(thread)
            
            for thread in threads:
                thread.join()

            if not all(results):
                print(f"Error downloading file {file_name}: One or more chunks failed to download.")
                return False

            if self.is_running:
                self.merge_chunk(file_name)
                self.downloaded_files.add(file_name)
                print(f"File {file_name} has been downloaded.\n")
                logging.info(f"[download_file] File {file_name} has been downloaded.\n")
                return True
        except Exception as e:
            print(f"Error: {e}")
            logging.error(f"Error: {e}")
            return False
        
    def cleanup_chunks(self, filename):
        """
        Xóa các phần chunk của file.
        """
        for part_number in range(4):
            part_filename = os.path.join(DIR_DOWNLOADED, f"{filename}.part{part_number}")
            if os.path.exists(part_filename):
                os.remove(part_filename)

    def start_client(self):
        while self.is_running:
            try:
                if not self.connect_to_server():
                    print("Trying to reconnect in 5 seconds...\n")
                    time.sleep(5)
                    continue
                
                new_files_to_download = self.monitor_input()
                for file in new_files_to_download:
                    if self.is_running:
                        if not self.download_file(file):
                            print(f"Error downloading {file}")

                time.sleep(5)
            except KeyboardInterrupt:
                self.handle_breaking(signal.SIGINT, None)
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(5)
        print("\33[JShut down...")

if __name__ == "__main__":
    SERVER_HOST = get_server_ip()
    SERVER_PORT = get_server_port()
    client = Client()
    client.start_client()