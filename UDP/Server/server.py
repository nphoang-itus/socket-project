import socket
import time
import os
import logging
import signal
import json
import sys
import struct
import threading

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 6264
MAX_RECEIVE_BYTES = 4096
CHUNK_BUFFER_SIZE = 8192
CHARACTER_ENCODING = "utf_8"
METADATA_FILE = "data.txt"
SERVER_FILE_DIRECTORY = "server_files"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s || %(levelname)s || %(message)s",
    handlers=[
        logging.FileHandler("server.log", mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)

class Server:
    def __init__(self):
        self.available_files = self.scan_available_files()
        self.is_running = True
        self.server_socket = None
        self.client_threads = []
        signal.signal(signal.SIGINT, self.shutdown_server) # Xử lý tắt server khi nhận tín hiệu SIGINT

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

    def scan_available_files(self):
        try:
            file_data = {}
            with open(METADATA_FILE, 'w') as outFile:
                for file in os.listdir(SERVER_FILE_DIRECTORY):
                    file_path = os.path.join(SERVER_FILE_DIRECTORY, file)
                    if os.path.isfile(file_path):
                        size_bytes = os.path.getsize(file_path)
                        size_readable = self.format_file_size(size_bytes)
                        file_data[file] = size_bytes
                        outFile.write(f"{file}: {size_readable}\n")
            
            return file_data

        except Exception as e:
            logging.error(f"[scan_available_files] Unexpected error: {e}")
            sys.exit(1)
    
    def shutdown_server(self, signum, frame):
        logging.info("Server is shutting down...")
        self.is_running = False

        for thread in self.client_threads:
            try:
                thread.join(timeout=1.0)
                logging.info(f"Thread {thread.name} successfully joined")
            except Exception as e:
                print(f"Error: {e}")
                logging.error(f"Error: {e}")

        self.client_threads.clear()

        if self.server_socket:
            try:
                self.server_socket.close()
                self.server_socket = None
            except Exception as e:
                logging.error(f"[shutdown_server] Error closing server: {e}")

        for handler in logging.getLogger().handlers:
            handler.flush()
            handler.close()
        
        time.sleep(3)
    
    def send_file_list(self, client_addr):
        if not self.available_files: # Nếu Ko có file trên server
            message = "ERROR: No files available to the client!"
            len_message = struct.pack("!I", len(message))
            self.server_socket.sendto(len_message, client_addr)
            self.server_socket.sendto(message.encode("utf_8"), client_addr)

            logging.info(f"Sent empty file list to {client_addr}")

            # Nếu ko có file trên server thì đóng server và chương trình để thêm file
            self.server_socket.close()
            self.server_socket = None
            sys.exit(1)

        json_data = json.dumps(self.available_files).encode(CHARACTER_ENCODING)
        len_json_data = struct.pack("!I", len(json_data))
        self.server_socket.sendto(len_json_data, client_addr)
        self.server_socket.sendto(json_data, client_addr)
        logging.info(f"[send_file_list] Sent file list to {client_addr}")

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

    def send_chunk(self, part_addr, file_name, offset_part, size_part, part_number):
        try:
            chunk_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            path_file = os.path.join(SERVER_FILE_DIRECTORY, file_name)
            with open(path_file, "rb") as inFile:
                inFile.seek(offset_part)
                seq_send = 0
                total_send = b""

                while len(total_send) < size_part:
                    remaining = size_part - len(total_send)
                    size_data_send = min(remaining, CHUNK_BUFFER_SIZE)
                    data = inFile.read(size_data_send)
                    
                    # checksum = sum(data) % 256
                    checksum = self.calc_checksum(data)
                    packet_format = f"!I I I {len(data)}s"
                    packet = struct.pack(packet_format, part_number, seq_send, checksum, data)

                    chunk_socket.sendto(packet, part_addr)
                    logging.info(f"[send_chunk] Sent {len(packet)} bytes for chunk {part_number}_{seq_send} to {part_addr}")

                    try:
                        chunk_socket.settimeout(10)  # Timeout chờ ACK/NAK
                        checking_data, _ = chunk_socket.recvfrom(MAX_RECEIVE_BYTES)
                        message = checking_data.decode(CHARACTER_ENCODING)

                        if message == f"ACK-{part_number}_{seq_send}":
                            logging.info(f"Received ACK for chunk {part_number}_{seq_send} from {part_addr}")
                            total_send += data
                            seq_send += 1
                        elif message == f"NAK-{part_number}_{seq_send}":
                            logging.warning(f"[send_chunk] NAK for chunk {part_number}_{seq_send}, retrying...")
                            continue
                    except socket.timeout:
                        logging.warning(f"[send_chunk] Timeout for chunk {part_number}_{seq_send}, retrying...")
                        continue
                    except Exception as e:
                        logging.error(f"[send_chunk] Error: {e}")
        except Exception as e:
            logging.error(f"[send_chunk] Error: {e}")
        finally:
            if chunk_socket:
                chunk_socket.close()

    def start_server(self):
        try:
            logging.info("[start_server] Server started and waiting for client requests.")

            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.bind((SERVER_HOST, SERVER_PORT))
            local_ip = socket.gethostbyname(socket.gethostname())

            logging.info(f"[start_server] Server initialized on {SERVER_HOST}:{SERVER_PORT}")
            logging.info(f"[start_server] Local IP address: {local_ip}")

            len_data, addr = self.server_socket.recvfrom(4)
            len_data = struct.unpack("!I", len_data)[0]
            data, addr = self.server_socket.recvfrom(len_data)

            message = data.decode(CHARACTER_ENCODING)
            logging.info(f"Received GET_FILE_LIST from {addr}: {message}")
            self.send_file_list(addr)
            self.server_socket.settimeout(1)
            
            while self.is_running:
                try:
                    if message == "GET_FILE_LIST":
                        while self.is_running:
                            part_data, part_addr = self.server_socket.recvfrom(MAX_RECEIVE_BYTES)
                            message_part = part_data.decode(CHARACTER_ENCODING)
                            logging.info(f"Received GET_CHUNK {part_addr}: {message_part}")
                            
                            if (message_part.startswith("GET_CHUNK")):
                                parts = message_part.strip().split('|')
                                _, file_name, offset_part, size_part, part_number = parts
                                offset_part = int(offset_part)
                                size_part = int(size_part)
                                part_number = int(part_number)

                            if self.is_running:
                                logging.info(f"Processing GET_CHUNK for {file_name}, chunk {part_number}, offset {offset_part}, size {size_part}")
                                client_thread = threading.Thread(target=self.send_chunk, args=(part_addr, file_name, offset_part, size_part, part_number), daemon=True)
                                client_thread.start()
                                self.client_threads.append(client_thread)
                except socket.timeout:
                    continue 
                except OSError:
                    break
        except KeyboardInterrupt:
            self.shutdown_server(signal.SIGINT, None)
            logging.info("Keyboard interrupt received")
        except Exception as e:
            self.shutdown_server(signal.SIGINT, None)
            logging.error(f"Unexpected error: {str(e)}")
        finally:
            if self.is_running:
                self.shutdown_server(signal.SIGINT, None)

            for handler in logging.getLogger().handlers:
                handler.flush()

if __name__ == '__main__':
    server = Server()
    server.start_server() # Khởi động server