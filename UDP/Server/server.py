import socket
import time
import os
import logging
import signal
import json
import sys
import struct
import threading

HOST = "0.0.0.0"
PORT = 6264
MAX_BYTES_RECV = 4096
BUFFER_SIZE = 1024
CHAR_ENCODING = "utf_8"
DATA_TXT = "data.txt"
FILE_DIR = "Files_onServer"

logging.basicConfig(
    filename = "server.log",
    level = logging.INFO,
    format = "%(asctime)s || %(levelname)s || %(message)s",
    filemode = 'w'
)

class Server:
    def __init__(self):
        self.file_data = self.scan_files_on_server()
        self.is_running = True
        self.server_socket = None
        self.enough_threads = False
        signal.signal(signal.SIGINT, self.handle_shutdown) # Xử lý tắt server khi nhận tín hiệu SIGINT

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

    def scan_files_on_server(self):
        try:
            file_data = {}
            with open(DATA_TXT, 'w') as outFile:
                for file in os.listdir(FILE_DIR):
                    file_path = os.path.join(FILE_DIR, file)
                    if os.path.isfile(file_path):
                        size_bytes = os.path.getsize(file_path)
                        size_readable = self.format_size(size_bytes)
                        file_data[file] = size_bytes
                        outFile.write(f"{file}: {size_readable}\n")
            
            return file_data

        except Exception as e:
            print(f"Unexpected error: {e}")
            logging.error(f"[scan_files_on_server] Unexpected error: {e}")
            sys.exit(1)
    
    def handle_shutdown(self, signum, frame):
        logging.info("Server is shutting down...")
        print("Server is shutting down...")
        self.is_running = False

        if self.server_socket:
            try:
                self.server_socket.close()
                self.server_socket = None
            except Exception as e:
                logging.error(f"[handle_shutdown] Error closing server: {e}")
                pass
    
    def send_file_list(self, client_addr):
        if not self.file_data: # Nếu Ko có file trên server
            message = "ERROR: No files available to the client!"
            self.server_socket.sendto(message.encode("utf_8"), client_addr)
            logging.info(f"Sent empty file list to {client_addr}")

            # Nếu ko có file trên server thì đóng server và chương trình để thêm file
            self.server_socket.close()
            self.server_socket = None
            sys.exit(1)

        json_data = json.dumps(self.file_data).encode(CHAR_ENCODING)
        self.server_socket.sendto(json_data, client_addr)
        logging.info(f"[send_file_list] Sent file list to {client_addr}")

    def send_chunk(self, part_addr, file_name, offset_part, size_part, part_number):
        try:
            chunk_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            path_file = os.path.join(FILE_DIR, file_name)
            with open(path_file, "rb") as inFile:
                inFile.seek(offset_part)
                seq_send = 0
                total_send = b""

                while len(total_send) < size_part:
                    if not self.enough_threads:
                        continue

                    remaining = size_part - len(total_send)
                    size_data_send = min(remaining, BUFFER_SIZE)
                    data = inFile.read(size_data_send)
                    
                    checksum = sum(data) % 256
                    packet_format = f"!I I B {len(data)}s"
                    packet = struct.pack(packet_format, part_number, seq_send, checksum, data)

                    chunk_socket.sendto(packet, part_addr)
                    logging.info(f"[send_chunk] Sent {len(packet)} bytes for chunk {part_number}_{seq_send} to {part_addr}")

                    try:
                        chunk_socket.settimeout(10)  # Timeout chờ ACK/NAK
                        checking_data, _ = chunk_socket.recvfrom(MAX_BYTES_RECV)
                        message = checking_data.decode(CHAR_ENCODING)

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
                        print(f"ERROR: {e}")
        except Exception as e:
            logging.error(f"[send_chunk] Error: {e}")
        finally:
            if chunk_socket:
                chunk_socket.close()

    def start_server(self):
        logging.info("[start_server] Server started and waiting for client requests.")
        print("Server started and waiting for client requests...")

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.bind((HOST, PORT))
        logging.info(f"[start_server] Server initialized on {HOST}:{PORT}")
        print(f"Server initialized on {HOST}:{PORT}")

        data, addr = self.server_socket.recvfrom(MAX_BYTES_RECV)
        message = data.decode("utf-8")
        logging.info(f"Received GET_FILE_LIST from {addr}: {message}")
        self.send_file_list(addr)
        while self.is_running:
            try:
                if message == "GET_FILE_LIST":
                    for i in range(4):
                        part_data, part_addr = self.server_socket.recvfrom(MAX_BYTES_RECV)
                        message_part = part_data.decode(CHAR_ENCODING)
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
                        
                        if i == 3:
                            self.enough_threads = True
            except KeyboardInterrupt:
                self.handle_shutdown(signal.SIGINT, None)
                break
            except Exception as e:
                print(f"Error: {e}")
                logging.error(f"Error: {e}")

if __name__ == '__main__':
    server = Server()
    server.start_server() # Khởi động server